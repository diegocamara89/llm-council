"""Testes puros do motor do council (agy simulado; nao gastam cota). Rodar: python tests/test_council.py"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import council  # noqa: E402
from agy import CallResult  # noqa: E402

FALHAS: list[str] = []


def check(nome: str, cond: bool, det: str = "") -> None:
    print(("  PASS  " if cond else "  FAIL  ") + nome + ("" if cond else f"  {det}"))
    if not cond:
        FALHAS.append(nome)


def falso(por_modelo: dict, chamadas: list, fase_revisor=None):
    """call_agy_parallel falso: responde pelo modelo (ou pela fase de revisao); registra os jobs."""
    def fn(jobs, **kw):
        out = []
        for j in jobs:
            chamadas.append(j)
            revisor = "pareceres anonimos" in j["prompt"]
            st, txt = (fase_revisor or {}).get(j["model"]) if revisor and fase_revisor and j["model"] in fase_revisor \
                else por_modelo.get(j["model"], ("OK", f"resposta de {j['model']}"))
            out.append(CallResult(st == "OK", txt if st == "OK" else "", j["model"], st, None, 1.0))
        return out
    return fn


def rodar(modo, por_modelo=None, contexto="CTX", fase_revisor=None, pergunta="Devo fazer X?", debate=False):
    chamadas: list = []
    council.call_agy_parallel = falso(por_modelo or {}, chamadas, fase_revisor)
    return council.rodar_council(pergunta, contexto, modo, seed=1, debate=debate), chamadas


def main() -> int:
    orig = council.call_agy_parallel
    try:
        print("[modos, chamadas e baldes]")
        out, ch = rodar("leve")
        check("leve: 3 conselheiros + presidente = 4 chamadas", out["status"] == "OK" and out["chamadas"] == 4, str(out["chamadas"]))
        check("leve: 3 modelos diferentes", len({j["model"] for j in ch[:3]}) == 3, str([j["model"] for j in ch[:3]]))
        check("leve: baldes 2 gemini + 2 claude", out["baldes"] == {"gemini": 2, "claude": 2}, str(out["baldes"]))
        check("presidente e o SYNTH_MODEL (Opus via agy)", ch[-1]["model"] == council.SYNTH_MODEL)
        check("presidente pede o fator ausente quando nao ha revisao", "ficou fora de todos os pareceres" in ch[-1]["prompt"])
        check("presidente recebe o contexto", "CTX" in ch[-1]["prompt"])
        out, ch = rodar("completo")
        check("completo: 5 + 3 revisores + presidente = 9 chamadas", out["chamadas"] == 9, str(out["chamadas"]))
        estranho = [j for j in ch[:5] if "quem chega agora" in j["prompt"]][0]
        check("estranho nao recebe o contexto", "CTX" not in estranho["prompt"])
        check("os outros conselheiros recebem o contexto", all("CTX" in j["prompt"] for j in ch[:5] if j is not estranho))
        check("revisor ve letras e nao a lente", "[A]" in ch[5]["prompt"] and "auditor" not in ch[5]["prompt"])
        check("mesmo modelo vale como um so", "valem como um so (" in ch[-1]["prompt"])
        check("conselheiro nao deve ler arquivos", "Nao leia arquivos" in ch[0]["prompt"])

        print("[cota e falhas]")
        out, ch = rodar("leve", {council.PRO: ("QUOTA_EXHAUSTED", "")})
        check("leve, cota Gemini: cadeira refeita no Sonnet e segue", out["status"] == "OK" and any("Sonnet" in a for a in out["avisos"]),
              str(out["avisos"]))
        out, ch = rodar("completo", {council.PRO: ("QUOTA_EXHAUSTED", ""), council.FLASH: ("QUOTA_EXHAUSTED", "")})
        check("completo, cota Gemini: conselheiros E revisores vao para o Sonnet e fecha", out["status"] == "OK" and out["veredito"],
              f"{out['status']} {out['avisos']}")
        out, ch = rodar("leve", {council.PRO: ("QUOTA_EXHAUSTED", ""), council.SONNET: ("QUOTA_EXHAUSTED", "")})
        check("cota Gemini e Claude: COTA", out["status"] == "COTA", out["status"])
        check("COTA nao chama o presidente", all(j["model"] != council.SYNTH_MODEL for j in ch))
        out, ch = rodar("leve", {council.SONNET: ("QUOTA_EXHAUSTED", "")})
        check("COTA preserva as respostas ja pagas", out["status"] == "COTA" and len(out["respostas"]) == 2, str(len(out["respostas"])))
        out, ch = rodar("leve", {council.PRO: ("ERROR", ""), council.FLASH: ("ERROR", "")})
        check("POUCAS_RESPOSTAS sem presidente e com a resposta que veio",
              out["status"] == "POUCAS_RESPOSTAS" and len(out["respostas"]) == 1 and all(j["model"] != council.SYNTH_MODEL for j in ch),
              out["status"])
        out, ch = rodar("completo", {council.FLASH: ("ERROR", "")})
        check("cadeira falhou: segue e avisa o presidente", out["status"] == "OK" and "Nao responderam" in ch[-1]["prompt"], out["status"])
        out, ch = rodar("completo", fase_revisor={council.PRO: ("ERROR", ""), council.SONNET: ("EMPTY", ""), council.FLASH: ("TIMEOUT", "")})
        check("revisores falhando geram aviso (nao silencio)", any("revisores sem resposta" in a for a in out["avisos"]), str(out["avisos"]))
        out, _ = rodar("leve", {council.SYNTH_MODEL: ("EMPTY", "")})
        check("presidente vazio vira SINTESE_FALHOU", out["status"] == "SINTESE_FALHOU" and not out["veredito"])

        print("[debate]")
        out, ch = rodar("leve", debate=True)
        check("leve + debate: 3 + 3 replicas + presidente = 7 chamadas", out["status"] == "OK" and out["chamadas"] == 7, str(out["chamadas"]))
        rodada2 = ch[3:6]
        check("replica usa o mesmo modelo da 1a rodada", [j["model"] for j in rodada2] == [r["modelo"] for r in out["respostas"]])
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
        longo = {m: ("OK", "x" * 9000) for m in (council.PRO, council.SONNET, council.FLASH)}
        out, ch = rodar("completo", longo, contexto="c" * 1000, pergunta="p" * 2900, debate=True)
        check("completo + debate com textos longos: todo prompt abaixo do teto",
              out["status"] == "OK" and max(len(j["prompt"]) for j in ch) < council.TETO_PROMPT, str(max(len(j["prompt"]) for j in ch)))
        # Replica falha so na 2a rodada: o falso decide pelo texto do prompt.
        chamadas: list = []
        def fn(jobs, **kw):
            res = []
            for j in jobs:
                chamadas.append(j)
                falha = "Segunda rodada" in j["prompt"] and j["model"] == council.FLASH
                res.append(CallResult(not falha, "" if falha else "r", j["model"], "ERROR" if falha else "OK", None, 1.0))
            return res
        council.call_agy_parallel = fn
        out = council.rodar_council("Devo X?", "", "leve", seed=1, debate=True)
        check("replica falhou: segue, avisa e fica o parecer original",
              out["status"] == "OK" and any("sem segunda rodada" in a for a in out["avisos"]), f"{out['status']} {out['avisos']}")
        def fn_cota(jobs, **kw):
            return [CallResult(False, "", j["model"], "QUOTA_EXHAUSTED", None, 1.0) if "Segunda rodada" in j["prompt"]
                    else CallResult(True, "r", j["model"], "OK", None, 1.0) for j in jobs]
        council.call_agy_parallel = fn_cota
        out = council.rodar_council("Devo X?", "", "leve", seed=1, debate=True)
        check("cota acabou no debate: COTA e respostas preservadas", out["status"] == "COTA" and len(out["respostas"]) == 3, out["status"])
        out, ch = rodar("leve", {council.PRO: ("QUOTA_EXHAUSTED", "")}, debate=True)
        check("cadeira que foi para a reserva replica na reserva", out["status"] == "OK" and all(j["model"] != council.PRO for j in ch if "Segunda rodada" in j["prompt"]), str(out["avisos"]))

        print("[tamanho e entrada]")
        longo = {m: ("OK", "x" * 9000) for m in (council.PRO, council.SONNET, council.FLASH)}
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
            import io, contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = council.main(["--prompts", "--pergunta", str(q), "--contexto", str(c)])
            check("--prompts leva o resumo de contexto (modo sigiloso)", rc == 0 and "RESUMO" in buf.getvalue())
            q.write_text("z" * 5000, encoding="utf-8")
            check("--prompts tambem valida o tamanho", council.main(["--prompts", "--pergunta", str(q)]) == 2)
            q.write_text("Devo X?", encoding="utf-8")
            check("--prompts com --debate e recusado", council.main(["--prompts", "--debate", "--pergunta", str(q)]) == 2)
        check("pasta de trabalho do agy nao e a pasta pessoal", council.CWD != Path.home())
    finally:
        council.call_agy_parallel = orig
    print("\nFALHAS: " + ", ".join(FALHAS) if FALHAS else "\nTODOS OS TESTES PASSARAM")
    return 1 if FALHAS else 0


if __name__ == "__main__":
    raise SystemExit(main())
