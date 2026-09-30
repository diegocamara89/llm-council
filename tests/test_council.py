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


def rodar(modo, por_modelo=None, contexto="CTX", fase_revisor=None, pergunta="Devo fazer X?"):
    chamadas: list = []
    council.call_agy_parallel = falso(por_modelo or {}, chamadas, fase_revisor)
    return council.rodar_council(pergunta, contexto, modo, seed=1), chamadas


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
        check("pasta de trabalho do agy nao e a pasta pessoal", council.CWD != Path.home())
    finally:
        council.call_agy_parallel = orig
    print("\nFALHAS: " + ", ".join(FALHAS) if FALHAS else "\nTODOS OS TESTES PASSARAM")
    return 1 if FALHAS else 0


if __name__ == "__main__":
    raise SystemExit(main())
