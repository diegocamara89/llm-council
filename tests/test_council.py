"""Testes puros do motor do council (Codex e vibe simulados; nao gastam cota). Rodar: python tests/test_council.py"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import council  # noqa: E402
CallResult = council.CallResult

FALHAS: list[str] = []
CODEX, GLM, LARGE = council.CODEX, council.GLM, council.LARGE
TODOS = (CODEX, GLM, LARGE)


def check(nome: str, cond: bool, det: str = "") -> None:
    print(("  PASS  " if cond else "  FAIL  ") + nome + ("" if cond else f"  {det}"))
    if not cond:
        FALHAS.append(nome)


def falso(por_modelo: dict, chamadas: list, fase_revisor=None, por_prompt=None):
    """Executor falso (serve para agy e para vibe): responde pelo modelo, pela fase de revisao ou por trecho
    do prompt (por_prompt tem prioridade); registra os jobs."""
    def fn(jobs, **kw):
        out = []
        for j in jobs:
            chamadas.append(j)
            revisor = "pareceres anonimos" in j["prompt"]
            hit = next((v for k, v in (por_prompt or {}).items() if k in j["prompt"]), None)
            if hit is not None:
                st, txt = hit
            elif revisor and fase_revisor and j["model"] in fase_revisor:
                st, txt = fase_revisor[j["model"]]
            else:
                st, txt = por_modelo.get(j["model"], ("OK", f"resposta de {j['model']}"))
            out.append(CallResult(st == "OK", txt if st == "OK" else "", j["model"], st, None, 1.0))
        return out
    return fn


def instala(fn) -> None:
    council.call_codex_parallel = fn
    council.call_vibe_parallel = fn


def rodar(modo, por_modelo=None, contexto="CTX", fase_revisor=None, pergunta="Devo fazer X?", debate=False,
          por_prompt=None):
    chamadas: list = []
    instala(falso(por_modelo or {}, chamadas, fase_revisor, por_prompt))
    return council.rodar_council(pergunta, contexto, modo, seed=1, debate=debate), chamadas


def main() -> int:
    orig_agy, orig_vibe = council.call_codex_parallel, council.call_vibe_parallel
    try:
        print("[modos, chamadas e baldes]")
        out, ch = rodar("leve")
        check("leve: 3 conselheiros + presidente = 4 chamadas", out["status"] == "OK" and out["chamadas"] == 4, str(out["chamadas"]))
        check("leve: 3 modelos de 3 familias", {j["model"] for j in ch[:3]} == {CODEX, GLM, LARGE}, str([j["model"] for j in ch[:3]]))
        check("leve: baldes 1 codex + 3 vibe", out["baldes"] == {"codex": 1, "vibe": 3}, str(out["baldes"]))
        check("presidente e o primeiro da cadeia (GLM 5.3 via vibe)", ch[-1]["model"] == council.PRESIDENTES[0] == GLM)
        check("presidente pede o fator ausente quando nao ha revisao", "ficou fora de todos os pareceres" in ch[-1]["prompt"])
        check("presidente recebe o contexto", "CTX" in ch[-1]["prompt"])
        out, ch = rodar("completo")
        check("completo: 5 + 3 revisores + presidente = 9 chamadas", out["chamadas"] == 9, str(out["chamadas"]))
        check("completo: 5 cadeiras em 3 modelos (repetem), sem Gemini", {j["model"] for j in ch[:5]} == set(TODOS) and not hasattr(council, "HYDROGEN") and not hasattr(council, "call_agy_parallel"))
        check("revisores: tres familias (OpenAI, Z.ai, Mistral)", {j["model"] for j in ch[5:8]} == {CODEX, GLM, LARGE})
        estranho = [j for j in ch[:5] if "quem chega agora" in j["prompt"]][0]
        check("estranho nao recebe o contexto", "CTX" not in estranho["prompt"])
        check("os outros conselheiros recebem o contexto", all("CTX" in j["prompt"] for j in ch[:5] if j is not estranho))
        check("revisor ve letras e nao a lente", "[A]" in ch[5]["prompt"] and "auditor" not in ch[5]["prompt"])
        check("conselheiro nao deve ler arquivos", "Nao leia arquivos" in ch[0]["prompt"])

        print("[reserva entre executores]")
        out, ch = rodar("leve", {CODEX: ("QUOTA_EXHAUSTED", "")})
        check("Codex sem cota: a cadeira vai para o vibe GLM e segue",
              out["status"] == "OK" and any("refeito em " + GLM in a for a in out["avisos"]), f"{out['status']} {out['avisos']}")
        out, ch = rodar("leve", {GLM: ("ERROR", ""), LARGE: ("QUOTA_EXHAUSTED", "")})
        check("vibe fora: cadeiras vao para o Codex e o presidente cai na cadeia ate o Codex",
              out["status"] == "OK" and any("refeito em " + CODEX in a for a in out["avisos"]) and ch[-1]["model"] == CODEX,
              f"{out['status']} {out['avisos']}")
        out, ch = rodar("completo", {CODEX: ("QUOTA_EXHAUSTED", "")})
        check("completo, Codex sem cota: conselheiros E revisores vao para o vibe e fecha",
              out["status"] == "OK" and out["veredito"], f"{out['status']} {out['avisos']}")
        out, ch = rodar("leve", {CODEX: ("QUOTA_EXHAUSTED", ""), GLM: ("QUOTA_EXHAUSTED", ""), LARGE: ("QUOTA_EXHAUSTED", "")})
        check("Codex e vibe sem cota: COTA", out["status"] == "COTA", out["status"])
        check("COTA nao chama o presidente", all("Voce fecha a analise" not in j["prompt"] for j in ch))
        out, ch = rodar("leve", {CODEX: ("QUOTA_EXHAUSTED", ""), GLM: ("QUOTA_EXHAUSTED", "")})
        check("COTA preserva as respostas ja pagas", out["status"] == "COTA" and len(out["respostas"]) == 1, str(len(out["respostas"])))
        out, ch = rodar("leve", {CODEX: ("ERROR", ""), GLM: ("ERROR", "")})
        check("POUCAS_RESPOSTAS sem presidente e com a resposta que veio",
              out["status"] == "POUCAS_RESPOSTAS" and len(out["respostas"]) == 1 and all("Voce fecha a analise" not in j["prompt"] for j in ch),
              out["status"])
        out, ch = rodar("completo", por_prompt={"lente e a opcao ausente": ("ERROR", "")})
        check("cadeira falhou nos dois executores: segue e avisa o presidente",
              out["status"] == "OK" and "Nao responderam" in ch[-1]["prompt"], out["status"])
        out, ch = rodar("completo", fase_revisor={CODEX: ("ERROR", ""), GLM: ("EMPTY", ""), LARGE: ("TIMEOUT", "")})
        check("revisores falhando geram aviso (nao silencio)", any("revisores sem resposta" in a for a in out["avisos"]), str(out["avisos"]))
        out, _ = rodar("leve", por_prompt={"Voce fecha a analise": ("EMPTY", "")})
        check("presidente vazio em toda a cadeia vira SINTESE_FALHOU", out["status"] == "SINTESE_FALHOU" and not out["veredito"])

        print("[debate]")
        out, ch = rodar("leve", debate=True)
        check("leve + debate: 3 + 3 replicas + presidente = 7 chamadas", out["status"] == "OK" and out["chamadas"] == 7, str(out["chamadas"]))
        rodada2 = ch[3:6]
        check("replica usa o mesmo modelo da 1a rodada", sorted(j["model"] for j in rodada2) == sorted(r["modelo"] for r in out["respostas"]))
        check("replicante ve o proprio parecer e os outros por letra",
              all("SEU PARECER NA PRIMEIRA RODADA ([" in j["prompt"] and j["prompt"].count("\n[") >= 2 for j in rodada2))
        check("toda resposta ganha replica", all(r["replica"] for r in out["respostas"]))
        check("presidente recebe a segunda rodada e a instrucao de mudanca", "segunda rodada]" in ch[-1]["prompt"] and "mudou de posicao" in ch[-1]["prompt"])
        out, ch = rodar("leve")
        check("sem debate nada muda: 4 chamadas e sem replica", out["chamadas"] == 4 and "replica" not in out["respostas"][0])
        out, ch = rodar("completo", debate=True)
        check("completo + debate: 5 + 5 + 3 + 1 = 14 chamadas", out["chamadas"] == 14, str(out["chamadas"]))
        check("revisor do completo ve a segunda rodada", "segunda rodada]" in ch[10]["prompt"])
        estranho2 = [j for j in ch[5:10] if "quem chega agora" in j["prompt"]][0]
        check("estranho continua sem contexto na replica", "CTX" not in estranho2["prompt"])
        longo = {m: ("OK", "x" * 9000) for m in TODOS}
        out, ch = rodar("completo", longo, contexto="c" * 1000, pergunta="p" * 2900, debate=True)
        check("completo + debate com textos longos: todo prompt abaixo do teto",
              out["status"] == "OK" and max(len(j["prompt"]) for j in ch) < council.TETO_PROMPT, str(max(len(j["prompt"]) for j in ch)))
        # Replica falha so na 2a rodada, nos dois executores de uma cadeira: fica o parecer original.
        out, ch = rodar("leve", debate=True, por_prompt={})  # base
        chamadas: list = []
        instala(falso({}, chamadas, por_prompt={"Segunda rodada": ("ERROR", "")}))
        out = council.rodar_council("Devo X?", "", "leve", seed=1, debate=True)
        check("replica falhou nos dois executores: segue, avisa e fica o parecer original",
              out["status"] == "OK" and any("sem segunda rodada" in a for a in out["avisos"]), f"{out['status']} {out['avisos']}")
        chamadas = []
        instala(falso({}, chamadas, por_prompt={"Segunda rodada": ("QUOTA_EXHAUSTED", "")}))
        out = council.rodar_council("Devo X?", "", "leve", seed=1, debate=True)
        check("cota acabou no debate (Codex e vibe): COTA e respostas preservadas", out["status"] == "COTA" and len(out["respostas"]) == 3, out["status"])
        out, ch = rodar("leve", {CODEX: ("QUOTA_EXHAUSTED", "")}, debate=True)
        check("cadeira que foi para a reserva replica na reserva",
              out["status"] == "OK" and all(j["model"] != CODEX for j in ch if "Segunda rodada" in j["prompt"]), str(out["avisos"]))

        print("[tamanho e entrada]")
        longo = {m: ("OK", "x" * 9000) for m in TODOS}
        out, ch = rodar("completo", longo, contexto="c" * 1000, pergunta="p" * 2900)
        check("respostas longas sao cortadas: prompt do presidente abaixo do teto",
              out["status"] == "OK" and len(ch[-1]["prompt"]) < council.TETO_PROMPT, str(len(ch[-1]["prompt"])))
        try:
            council.rodar_council("x" * 3000, "y" * 1500, "leve")
            check("pergunta + contexto acima do limite levanta", False)
        except ValueError:
            check("pergunta + contexto acima do limite levanta", True)
        with tempfile.TemporaryDirectory() as tmp:
            q = Path(tmp) / "q.txt"; c = Path(tmp) / "c.txt"
            q.write_text("Devo X?", encoding="utf-8"); c.write_text("RESUMO", encoding="utf-8")
            check("CLI: arquivo inexistente sai 2", council.main(["--pergunta", str(Path(tmp) / "nao.txt")]) == 2)
            import contextlib
            import io
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = council.main(["--prompts", "--pergunta", str(q), "--contexto", str(c)])
            check("--prompts leva o resumo de contexto (reserva sem Codex e vibe)", rc == 0 and "RESUMO" in buf.getvalue())
            q.write_text("z" * 5000, encoding="utf-8")
            check("--prompts tambem valida o tamanho", council.main(["--prompts", "--pergunta", str(q)]) == 2)
            q.write_text("Devo X?", encoding="utf-8")
            check("--prompts com --debate e recusado", council.main(["--prompts", "--debate", "--pergunta", str(q)]) == 2)
        check("pasta de trabalho nao e a pasta pessoal", council.CWD != Path.home())

        print("[executor vibe]")
        council.call_vibe_parallel = orig_vibe          # volta ao real para testar o parser
        orig_run, orig_which = subprocess.run, council.shutil.which

        def fake_run(saida: str, err: str = "", rc: int = 0):
            def fn(argv, **kw):
                return subprocess.CompletedProcess(argv, rc, saida, err)
            return fn
        council.shutil.which = lambda _n: "vibe"
        try:
            ok = json.dumps([{"type": "message", "role": "assistant", "content": [{"text": "parecer X"}]}])
            subprocess.run = fake_run(ok)
            r = council._vibe_um("p", LARGE, 5)
            check("vibe: resposta do assistente vira OK com o texto", r.ok and r.text == "parecer X" and r.status == "OK", str(r))
            subprocess.run = fake_run("[]")
            check("vibe: saida sem texto vira EMPTY", council._vibe_um("p", LARGE, 5).status == "EMPTY")
            subprocess.run = fake_run("", "boom", 1)
            check("vibe: rc diferente de zero sem texto vira ERROR", council._vibe_um("p", LARGE, 5).status == "ERROR")
            subprocess.run = fake_run("", "", 3)
            check("vibe: rc 3 (limite de tempo) vira TIMEOUT", council._vibe_um("p", LARGE, 5).status == "TIMEOUT")
            subprocess.run = fake_run("", "429 rate limit exceeded", 1)
            check("vibe: mensagem de limite vira QUOTA_EXHAUSTED", council._vibe_um("p", LARGE, 5).status == "QUOTA_EXHAUSTED")

            def estoura(argv, **kw):
                raise subprocess.TimeoutExpired(argv, 1)
            subprocess.run = estoura
            check("vibe: processo que estoura o tempo vira TIMEOUT", council._vibe_um("p", LARGE, 5).status == "TIMEOUT")
            council.shutil.which = lambda _n: None
            check("vibe ausente no PATH vira ERROR claro", "PATH" in (council._vibe_um("p", LARGE, 5).error or ""))
        finally:
            subprocess.run, council.shutil.which = orig_run, orig_which

        seq = {"n": 0}
        orig_um = council._vibe_um
        def um_vazio_depois_ok(p, m, t):
            seq["n"] += 1
            return CallResult(seq["n"] > 1, "ok" if seq["n"] > 1 else "", m, "OK" if seq["n"] > 1 else "EMPTY", None, 0.1)
        council._vibe_um = um_vazio_depois_ok
        try:
            r = council.call_vibe_parallel([{"prompt": "p", "model": LARGE}], retries=2)[0]
            check("vibe paralelo: vazio e retentado e depois da certo", r.ok and seq["n"] == 2, str(seq))
            seq["n"] = 0
            council._vibe_um = lambda p, m, t: (seq.__setitem__("n", seq["n"] + 1) or CallResult(False, "", m, "QUOTA_EXHAUSTED", None, 0.1))
            r = council.call_vibe_parallel([{"prompt": "p", "model": LARGE}], retries=2)[0]
            check("vibe paralelo: cota nao e retentada", r.status == "QUOTA_EXHAUSTED" and seq["n"] == 1, str(seq))
        finally:
            council._vibe_um = orig_um

        print("[modelos escolhidos pelo ambiente]")
        scripts = Path(__file__).resolve().parent.parent / "scripts"
        env = {**__import__("os").environ, "COUNCIL_CODEX_MODEL": "x-codex", "COUNCIL_VIBE_MODEL_1": "v1", "COUNCIL_VIBE_MODEL_2": "v2"}
        out = subprocess.run([sys.executable, "-c", f"import sys; sys.path.insert(0, r'{scripts}'); import council; "
                              "print(council.CODEX, council.GLM, council.LARGE)"], capture_output=True, text=True, env=env).stdout.strip()
        check("variaveis de ambiente escolhem os modelos do conselho", out == "codex:x-codex vibe:v1 vibe:v2", out)
        print("[executor codex]")
        council.call_codex_parallel = orig_agy      # volta ao real para testar o parser
        orig_run2, orig_which2 = subprocess.run, council.shutil.which
        council.shutil.which = lambda _n: "codex"
        try:
            def fake_codex(texto_saida, err="", rc=0):
                def fn(argv, **kw):
                    if texto_saida is not None:     # o codex grava a resposta no arquivo do -o
                        Path(argv[argv.index("-o") + 1]).write_text(texto_saida, encoding="utf-8")
                    return subprocess.CompletedProcess(argv, rc, "", err)
                return fn
            subprocess.run = fake_codex("\u2705 **RESULTADO:** parecer X")
            r = council._codex_um("p", CODEX, 5)
            check("codex: texto do -o vira OK e perde o rotulo do Painel", r.ok and r.text == "parecer X", str(r))
            subprocess.run = fake_codex("")
            check("codex: arquivo vazio com rc 0 vira EMPTY", council._codex_um("p", CODEX, 5).status == "EMPTY")
            subprocess.run = fake_codex(None, "boom", 1)
            check("codex: rc 1 sem arquivo vira ERROR", council._codex_um("p", CODEX, 5).status == "ERROR")
            subprocess.run = fake_codex(None, "You have hit your usage limit", 1)
            check("codex: limite de uso vira QUOTA_EXHAUSTED", council._codex_um("p", CODEX, 5).status == "QUOTA_EXHAUSTED")

            def estoura2(argv, **kw):
                raise subprocess.TimeoutExpired(argv, 1)
            subprocess.run = estoura2
            check("codex: passou do tempo vira TIMEOUT", council._codex_um("p", CODEX, 5).status == "TIMEOUT")
            visto: list = []

            def captura(argv, **kw):
                visto[:] = argv
                Path(argv[argv.index("-o") + 1]).write_text("x", encoding="utf-8")
                return subprocess.CompletedProcess(argv, 0, "", "")
            subprocess.run = captura
            council._codex_um("p", CODEX, 5)
            check("codex: so leitura, modelo certo e pasta propria",
                  visto[visto.index("-s") + 1] == "read-only" and visto[visto.index("-m") + 1] == "gpt-6.1-sol" and visto[visto.index("-C") + 1] == str(council.CWD), str(visto))
            council.shutil.which = lambda _n: None
            check("codex ausente vira ERROR claro", "PATH" in (council._codex_um("p", CODEX, 5).error or ""))
        finally:
            subprocess.run, council.shutil.which = orig_run2, orig_which2
    finally:
        council.call_codex_parallel, council.call_vibe_parallel = orig_agy, orig_vibe
    print("\nFALHAS: " + ", ".join(FALHAS) if FALHAS else "\nTODOS OS TESTES PASSARAM")
    return 1 if FALHAS else 0


if __name__ == "__main__":
    raise SystemExit(main())
