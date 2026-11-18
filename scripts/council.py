"""
council.py - motor do /llm-council sobre dois executores: agy (Antigravity CLI, modelos Gemini 4)
e vibe (Mistral Vibe CLI, modelos Mistral e GLM). Modelo do vibe aparece como "vibe:<apelido>".

Modos:
    leve     (padrao) 3 conselheiros sem revisao cruzada; presidente Mistral Large 4.
    completo 5 conselheiros + 3 revisores anonimos; presidente Mistral Large 4.
    --debate (em qualquer modo) segunda rodada: cada conselheiro le os outros pareceres e rebate.
Se um executor cai (cota, erro, vazio, timeout), a cadeira e refeita no outro (agy -> vibe GLM 5.3;
vibe -> agy Hydrogen High). Sem nenhum dos dois, --prompts gera os prompts para subagentes do Claude.

Uso:
    python council.py --modo leve [--debate] --pergunta pergunta.txt [--contexto contexto.txt]
    python council.py --prompts --modo leve --pergunta pergunta.txt [--contexto contexto.txt]
Saida: JSON no stdout; progresso por fase no stderr.
Codigo: 0 ok, 1 o conselho nao fechou, 2 entrada invalida, 3 cota esgotada (agy e vibe).
"""
from __future__ import annotations

import argparse
import json
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path.home() / ".claude" / "skills" / "call-agy" / "scripts"))
from agy import CallResult, call_agy_parallel  # noqa: E402

# Pasta vazia de trabalho do agy: sem ela ele comecaria na pasta pessoal do usuario.
CWD = Path.home() / ".agy-council-cwd"
LIMITE_PERGUNTA = 4000    # pergunta + contexto
CORTE_RESPOSTA = 3000     # cada resposta, ao entrar no prompt de revisor/presidente
CORTE_REVISAO = 2000
CORTE_DEBATE = 1500       # com --debate, cada parecer da 1a rodada cabe em menos (a replica vem junto)
CORTE_REPLICA = 2000
TETO_PROMPT = 30000       # o prompt vai por argv (limite do Windows ~32767)

# Modelos (decisao de 17/11/2026: Claude Opus/Sonnet saem do agy; cadeiras por diversidade de familia,
# sem nota medida de julgamento; so entra modelo com nota 1,00 ou quase nas baterias da avaliacao-vibe:
# o Argon errou fato atual da web e o Carbon estourou 300 s no conselho: os dois ficaram de fora). Executor agy: ID literal do catalogo. Executor vibe: "vibe:<apelido>".
HYDROGEN = "Gemini 4 Hydrogen (High)"
GLM = "vibe:zai-glm-5-3"
LARGE = "vibe:mistral-large-4"
# executor caiu -> a cadeira vai para o outro: agy -> vibe GLM 5.3; vibe -> agy Hydrogen High.
RESERVA = {"agy": GLM, "vibe": HYDROGEN}
PRESIDENTES = [LARGE, GLM, HYDROGEN]   # tenta nesta ordem; so o ultimo e do agy
VIBE_TIMEOUT = 300
AGY_TIMEOUT = 240   # Hydrogen: 47-131 s em tarefas simples, 118-159 s no conselho real; passou disso, cai na reserva do vibe
AGY_RETRIES = 1

# papel -> (lente, modelo). Lentes proprias (tres delas ecoam perspectivas classicas de analise; as de
# evidencia e alternativa sao desta skill), inspiradas no metodo de Karpathy e na skill de Ole Lehmann.
PAPEIS: dict[str, tuple[str, str]] = {
    "auditor": ("Sua lente e o risco. Liste o que pode falhar, quanto custa se falhar e qual premissa "
                "sustenta a proposta sem prova.", HYDROGEN),
    "evidencia": ("Sua lente e a prova. Diga que dado, medicao ou teste barato decidiria a questao, e o que "
                  "hoje esta sendo afirmado sem esse dado.", GLM),
    "operador": ("Sua lente e a execucao. Diga o menor passo verificavel desta semana, o esforco e o que "
                 "o resultado desse passo provaria.", LARGE),
    "alternativa": ("Sua lente e a opcao ausente. Diga que outro caminho, fora das opcoes dadas, usaria o "
                    "mesmo esforco com resultado melhor.", HYDROGEN),
    "estranho": ("Sua lente e a de quem chega agora, sem historico. Diga o que soa estranho, obscuro ou "
                 "desproporcional.", GLM),
}
MODOS = {"leve": ["auditor", "evidencia", "operador"],
         "completo": ["auditor", "evidencia", "operador", "alternativa", "estranho"]}
MINIMO = {"leve": 2, "completo": 3}
REVISORES = [HYDROGEN, GLM, LARGE]   # tres familias: Gemini, Z.ai, Mistral


def _corta(texto: str, n: int) -> str:
    return texto if len(texto) <= n else texto[:n] + " [cortado]"


def prompt_conselheiro(papel: str, pergunta: str, contexto: str) -> str:
    lente, _ = PAPEIS[papel]
    # "estranho" recebe so a pergunta: o papel dele depende de nao ter o contexto.
    corpo = pergunta if papel == "estranho" or not contexto else f"{pergunta}\n\nCONTEXTO:\n{contexto}"
    return (
        f"Voce opina numa decisao ao lado de outros analistas. {lente}\n"
        "Nao leia arquivos nem rode comandos: use so o texto abaixo. Escreva em portugues do Brasil, "
        "no maximo 300 palavras, com posicao definida e as incertezas declaradas. Nao diga qual e a sua lente.\n"
        "Feche com: 'Premissas que assumi:' e 'O que mudaria minha opiniao:'.\n\n"
        f"DECISAO EM ANALISE:\n{corpo}"
    )


def _anonimo(respostas: list[dict]) -> str:
    # Com debate, a replica de cada letra vai junto e o parecer original encolhe para caber no teto.
    corte = CORTE_DEBATE if any(r.get("replica") for r in respostas) else CORTE_RESPOSTA
    return "\n\n".join(
        f"[{r['letra']}]\n{_corta(r['texto'], corte)}"
        + (f"\n\n[{r['letra']}, segunda rodada]\n{_corta(r['replica'], CORTE_REPLICA)}" if r.get("replica") else "")
        for r in respostas)


def prompt_debate(papel: str, pergunta: str, contexto: str, propria: dict, respostas: list[dict]) -> str:
    lente, _ = PAPEIS[papel]
    corpo = pergunta if papel == "estranho" or not contexto else f"{pergunta}\n\nCONTEXTO:\n{contexto}"
    outras = "\n\n".join(f"[{r['letra']}]\n{_corta(r['texto'], CORTE_RESPOSTA)}" for r in respostas if r is not propria)
    return (
        f"Segunda rodada de uma analise em grupo. {lente}\n"
        "Nao leia arquivos nem rode comandos: use so o texto abaixo. Em portugues do Brasil, no maximo 250 "
        "palavras: (1) rebata a afirmacao mais fragil de cada outro parecer, citando a letra; (2) diga o que "
        "algum deles trouxe que muda a sua posicao, ou declare que nada mudou; (3) termine com 'Posicao final:' "
        "em uma frase. Mude de ideia so diante de argumento ou dado novo; nao ceda a tom nem a maioria.\n\n"
        f"DECISAO EM ANALISE:\n{corpo}\n\nSEU PARECER NA PRIMEIRA RODADA ([{propria['letra']}]):\n"
        f"{_corta(propria['texto'], CORTE_RESPOSTA)}\n\nPARECERES DOS OUTROS:\n{outras}"
    )


def prompt_revisor(pergunta: str, respostas: list[dict]) -> str:
    return (
        "Voce recebe pareceres anonimos, marcados por letra, sobre a mesma decisao. Em portugues do Brasil, "
        "ate 200 palavras, faca tres coisas: aponte a afirmacao mais fragil de cada parecer; diga que "
        "evidencia resolveria a principal discordancia entre eles; e cite um fator capaz de mudar a "
        "decisao que nao aparece em parecer algum.\n\n"
        f"DECISAO:\n{pergunta}\n\n{_anonimo(respostas)}"
    )


def prompt_presidente(pergunta: str, contexto: str, respostas: list[dict], revisoes: list[str],
                      faltaram: list[str]) -> str:
    grupos: dict[str, list[str]] = {}
    for r in respostas:
        grupos.setdefault(r["modelo"], []).append(r["letra"])
    mesmo = "; ".join(" e ".join(v) for v in grupos.values() if len(v) > 1)
    debate = any(r.get("replica") for r in respostas)
    partes = [
        "Voce fecha a analise de um grupo. Escreva em portugues do Brasil nesta ordem: "
        "### Resposta curta (uma frase) / ### Argumentos que se sustentam / ### Riscos e lacunas / "
        "### Desacordo que continua / ### Premissas a conferir (fatos verificaveis de que a resposta "
        "depende) / ### Proximo passo.",
        "Pareceres do MESMO modelo valem como um so" + (f" ({mesmo})." if mesmo else "."),
        "Posicao firme nao e prova: pese pelos argumentos, nao pelo tom.",
    ]
    if debate:
        partes.append("Houve segunda rodada: cada analista leu os outros e rebateu. Diga quem mudou de posicao e "
                      "por qual argumento; mudanca sem argumento novo nao conta como convergencia.")
    if not revisoes:
        partes.append("Nao houve revisao cruzada: cite voce o fator capaz de mudar a decisao que ficou fora de todos os pareceres.")
    if faltaram:
        partes.append("Nao responderam (nao invente o que diriam): " + ", ".join(faltaram) + ".")
    partes.append(f"DECISAO:\n{pergunta}" + (f"\n\nCONTEXTO:\n{contexto}" if contexto else ""))
    partes.append(_anonimo(respostas))
    if revisoes:
        partes.append("REVISOES:\n" + "\n\n".join(_corta(r, CORTE_REVISAO) for r in revisoes))
    return "\n\n".join(partes)


def _balde(modelo: str) -> str:
    return "vibe" if modelo.startswith("vibe:") else "agy"


# Padrao para erro de cota/limite na saida do vibe. NAO verificado contra um limite real do vibe: se o
# padrao nao casar, o erro vira ERROR e a cadeira cai na reserva do mesmo jeito (so muda o rotulo do status).
_RE_COTA_VIBE = re.compile(r"quota|rate.?limit|usage limit|insufficient|credit|\b429\b", re.I)


def _vibe_um(prompt: str, modelo: str, timeout: int) -> CallResult:
    """Uma chamada ao vibe em modo programatico. Devolve CallResult (OK | EMPTY | ERROR | TIMEOUT | QUOTA_EXHAUSTED)."""
    t0 = time.time()
    exe = shutil.which("vibe")
    if not exe:
        return CallResult(False, "", modelo, "ERROR", "vibe nao encontrado no PATH", 0.0)
    CWD.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        pf = Path(tmp) / "prompt.txt"
        pf.write_text(prompt, encoding="utf-8")
        argv = [exe, "--prompt-file", str(pf), "--output", "json", "--max-turns", "6", "--time-limit", str(timeout),
                "--workdir", str(CWD), "--output-dir", str(Path(tmp) / "out"), "--trust",
                "--model", modelo.split(":", 1)[1]]
        try:
            p = subprocess.run(argv, input="", capture_output=True, text=True, encoding="utf-8", errors="replace",
                               timeout=timeout + 60)
            out, err, rc = p.stdout, p.stderr, p.returncode
        except subprocess.TimeoutExpired:
            return CallResult(False, "", modelo, "TIMEOUT", None, time.time() - t0)
    texto = ""
    try:
        for e in json.loads(out):
            if e.get("type") == "message" and e.get("role") == "assistant":
                t = "".join(c.get("text", "") for c in e.get("content", []) if isinstance(c, dict))
                if t.strip():
                    texto = t
    except Exception:  # noqa: BLE001
        texto = out if rc == 0 else ""
    seg = time.time() - t0
    if texto.strip():
        return CallResult(True, texto.strip(), modelo, "OK", None, seg)
    if rc == 3:
        return CallResult(False, "", modelo, "TIMEOUT", None, seg)
    if _RE_COTA_VIBE.search(out + err):
        return CallResult(False, "", modelo, "QUOTA_EXHAUSTED", (err or out)[:300], seg)
    return CallResult(False, "", modelo, "EMPTY" if rc == 0 else "ERROR", (err or out)[:300], seg)


def call_vibe_parallel(jobs: list[dict], max_concurrency: int = 3, retries: int = 2,
                       timeout: int = VIBE_TIMEOUT, **_kw) -> list[CallResult]:
    """Como call_agy_parallel, para modelos "vibe:<apelido>". Retenta erro, vazio e timeout (cota nao)."""
    def um(j: dict) -> CallResult:
        r = _vibe_um(j["prompt"], j["model"], timeout)
        for _ in range(retries):
            if r.status not in ("ERROR", "EMPTY", "TIMEOUT"):
                break
            r = _vibe_um(j["prompt"], j["model"], timeout)
        return r
    with ThreadPoolExecutor(max_workers=max_concurrency) as ex:
        return list(ex.map(um, jobs))


def _chamar(jobs: list[dict]) -> list:
    """Despacha cada job ao executor do seu modelo (agy e vibe em paralelo) e devolve na mesma ordem."""
    res: list = [None] * len(jobs)
    grupos = {"agy": [i for i, j in enumerate(jobs) if _balde(j["model"]) == "agy"],
              "vibe": [i for i, j in enumerate(jobs) if _balde(j["model"]) == "vibe"]}

    def roda(b: str) -> None:
        idx = grupos[b]
        if not idx:
            return
        sub = [jobs[i] for i in idx]
        if b == "agy":
            rs = call_agy_parallel(sub, max_concurrency=5, retries=AGY_RETRIES, timeout=AGY_TIMEOUT, cwd=str(CWD))
        else:
            rs = call_vibe_parallel(sub, max_concurrency=3, retries=2, timeout=VIBE_TIMEOUT)
        for i, r in zip(idx, rs):
            res[i] = r

    with ThreadPoolExecutor(max_workers=2) as ex:
        list(ex.map(roda, ["agy", "vibe"]))
    return res


def _rodar(fase: str, jobs: list[dict], rotulos: list[str], out: dict, reserva: bool = True):
    """Roda a fase. Pedido que falhou (cota, erro, vazio, timeout) e refeito no outro executor
    (agy -> vibe GLM 5.3; vibe -> agy Hydrogen High). Devolve (resultados, jobs)."""
    CWD.mkdir(exist_ok=True)
    for j in jobs:
        if len(j["prompt"]) > TETO_PROMPT:
            raise ValueError(f"prompt de {fase} com {len(j['prompt'])} caracteres passa do teto {TETO_PROMPT}")
    res = _chamar(jobs)
    for j in jobs:
        out["baldes"][_balde(j["model"])] += 1
    out["chamadas"] += len(jobs)
    refazer = [i for i, r in enumerate(res) if reserva and not (r.ok and r.text.strip())]
    if refazer:
        out["avisos"].append(f"{fase}: " + "; ".join(
            f"{rotulos[i]} falhou em {jobs[i]['model']} ({res[i].status}), refeito em {RESERVA[_balde(jobs[i]['model'])]}"
            for i in refazer))
        for i in refazer:
            jobs[i] = {**jobs[i], "model": RESERVA[_balde(jobs[i]["model"])]}
        novos = _chamar([jobs[i] for i in refazer])
        for i, r in zip(refazer, novos):
            res[i] = r
            out["baldes"][_balde(jobs[i]["model"])] += 1
        out["chamadas"] += len(refazer)
    for rot, r in zip(rotulos, res):
        print(f"[{fase}] {rot}: {r.status} ({r.model}, {r.elapsed_s:.0f}s)", file=sys.stderr, flush=True)
    return res, jobs


def rodar_council(pergunta: str, contexto: str = "", modo: str = "leve", seed: int | None = None,
                  debate: bool = False) -> dict:
    """Devolve {status, modo, debate, veredito, respostas, revisoes, chamadas, baldes, avisos}.

    status: OK | COTA (cota esgotada no agy E no vibe) | POUCAS_RESPOSTAS | SINTESE_FALHOU.
    `respostas` volta preenchida mesmo quando o conselho nao fecha (o que ja foi pago nao se perde).
    `chamadas` conta pedidos ao agy e ao vibe, sem as retentativas internas (refazer na reserva conta).
    Com `debate`, cada resposta ganha `replica` (segunda rodada; "" se aquela cadeira falhou).
    """
    if modo not in MODOS:
        raise ValueError(f"modo invalido: {modo!r}")
    if len(pergunta) + len(contexto) > LIMITE_PERGUNTA:
        raise ValueError(f"pergunta + contexto passam de {LIMITE_PERGUNTA} caracteres: resuma antes")
    papeis = MODOS[modo]
    out = {"status": "OK", "modo": modo, "debate": debate, "veredito": "", "respostas": [], "revisoes": [],
           "chamadas": 0, "baldes": {"agy": 0, "vibe": 0}, "avisos": []}

    jobs = [{"prompt": prompt_conselheiro(p, pergunta, contexto), "model": PAPEIS[p][1]} for p in papeis]
    res, jobs = _rodar("conselheiros", jobs, papeis, out)

    boas = [(p, j["model"], r.text.strip()) for p, j, r in zip(papeis, jobs, res) if r.ok and r.text.strip()]
    faltaram = [f"{p} ({r.status})" for p, r in zip(papeis, res) if not (r.ok and r.text.strip())]
    # Letras sorteadas por codigo: quem revisa nao sabe qual lente escreveu o que.
    sorteio = random.Random(seed) if seed is not None else random.SystemRandom()
    sorteio.shuffle(boas)
    respostas = [{"letra": chr(65 + i), "papel": p, "modelo": m, "texto": t} for i, (p, m, t) in enumerate(boas)]
    out["respostas"] = respostas

    if any(r.status == "QUOTA_EXHAUSTED" for r in res):
        out.update(status="COTA")
        out["avisos"].append("cota esgotada no agy e no vibe: trocar a conta do agy e conferir o painel do vibe")
        return out
    if len(boas) < MINIMO[modo]:
        out.update(status="POUCAS_RESPOSTAS")
        out["avisos"].append("nao responderam: " + ", ".join(faltaram))
        return out

    if debate:
        # Mesma lente e mesmo modelo da 1a rodada (o modelo ja trocado pela reserva, se foi o caso).
        djobs = [{"prompt": prompt_debate(r["papel"], pergunta, contexto, r, respostas), "model": r["modelo"]}
                 for r in respostas]
        dv, djobs = _rodar("debate", djobs, [r["letra"] for r in respostas], out)
        for r, j, d in zip(respostas, djobs, dv):
            r["replica"] = d.text.strip() if d.ok else ""
            if j["model"] != r["modelo"]:
                r["modelo_replica"] = j["model"]
        if any(d.status == "QUOTA_EXHAUSTED" for d in dv):
            out.update(status="COTA")
            out["avisos"].append("cota esgotada no agy e no vibe durante o debate: trocar a conta do agy e conferir o painel do vibe")
            return out
        sem = [f"{r['letra']} ({d.status})" for r, d in zip(respostas, dv) if not r["replica"]]
        if sem:
            out["avisos"].append("sem segunda rodada (fica so o parecer original): " + ", ".join(sem))

    if modo == "completo":
        rjobs = [{"prompt": prompt_revisor(pergunta, respostas), "model": m} for m in REVISORES]
        rv, rjobs = _rodar("revisao", rjobs, REVISORES, out)
        if any(r.status == "QUOTA_EXHAUSTED" for r in rv):
            out.update(status="COTA")
            out["avisos"].append("cota esgotada no agy e no vibe na revisao: trocar a conta do agy e conferir o painel do vibe")
            return out
        out["revisoes"] = [f"(revisor {j['model']}) {r.text.strip()}" for j, r in zip(rjobs, rv) if r.ok and r.text.strip()]
        falhos = [f"{j['model']} ({r.status})" for j, r in zip(rjobs, rv) if not (r.ok and r.text.strip())]
        if falhos:
            out["avisos"].append("revisores sem resposta: " + ", ".join(falhos))

    # Presidente: tenta a cadeia PRESIDENTES na ordem (cada tentativa sem a reserva automatica).
    ptexto = prompt_presidente(pergunta, contexto, respostas, out["revisoes"], faltaram)
    pres = None
    for pm in PRESIDENTES:
        [pres], _ = _rodar("presidente", [{"prompt": ptexto, "model": pm}], ["presidente"], out, reserva=False)
        if pres.ok and pres.text.strip():
            break
        out["avisos"].append(f"presidente {pm}: {pres.status}")
    if pres.status == "QUOTA_EXHAUSTED":
        out.update(status="COTA")
        out["avisos"].append("cota esgotada no presidente (toda a cadeia): trocar a conta do agy e conferir o painel do vibe")
    elif not (pres.ok and pres.text.strip()):
        out.update(status="SINTESE_FALHOU")
        out["avisos"].append(f"presidente: {pres.status} {pres.error or ''}".strip())
    else:
        out["veredito"] = pres.text.strip()
    if faltaram:
        out["avisos"].append("conselheiros sem resposta: " + ", ".join(faltaram))
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Motor do /llm-council sobre o agy e o vibe.")
    ap.add_argument("--modo", default="leve", choices=list(MODOS))
    ap.add_argument("--pergunta", required=True, help="arquivo .txt com a pergunta enquadrada")
    ap.add_argument("--contexto", help="arquivo .txt com o resumo de contexto escrito pelo Claude")
    ap.add_argument("--prompts", action="store_true", help="so imprime os prompts (reserva: subagentes do Claude)")
    ap.add_argument("--debate", action="store_true", help="segunda rodada: cada conselheiro rebate os outros")
    a = ap.parse_args(argv)
    try:
        pergunta = Path(a.pergunta).read_text(encoding="utf-8").strip()
        contexto = Path(a.contexto).read_text(encoding="utf-8").strip() if a.contexto else ""
        if len(pergunta) + len(contexto) > LIMITE_PERGUNTA:
            raise ValueError(f"pergunta + contexto passam de {LIMITE_PERGUNTA} caracteres: resuma antes")
        if a.prompts and a.debate:
            raise ValueError("--debate nao vale com --prompts: no modo sigiloso as visoes sao do mesmo modelo")
        if a.prompts:
            print(json.dumps({p: prompt_conselheiro(p, pergunta, contexto) for p in MODOS[a.modo]},
                             ensure_ascii=False, indent=2))
            return 0
        out = rodar_council(pergunta, contexto, a.modo, debate=a.debate)
    except (OSError, ValueError) as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 3 if out["status"] == "COTA" else (0 if out["status"] == "OK" else 1)


if __name__ == "__main__":
    raise SystemExit(main())
