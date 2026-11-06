"""LLM step: question -> JSON {sql, graphique, hypotheses, refus}, validated by pydantic, one repair attempt with the exact error.
The model only ever proposes; guard.check + the read-only executor decide what runs."""
import json
import time
from pathlib import Path
from typing import Optional
import yaml
from pydantic import BaseModel, ValidationError
from .guard import check, Rejected

MODEL = "qwen3.5:4b"
CATALOG = yaml.safe_load((Path(__file__).parent / "catalog.yaml").read_text(encoding="utf8"))

# Few-shot examples come from the dev set only (never from test).
SHOTS = [
    ("Quelle est la VaR du book TAUX_EUR au dernier jour ?", "SELECT var99_1j_eur FROM v_risque_book WHERE book='TAUX_EUR' AND date=(SELECT max(date) FROM v_risque_book)"),
    ("Quels sont les 3 traders avec le plus grand DV01 absolu au dernier jour ?", "SELECT trader, sum(abs(dv01_eur)) AS d FROM v_positions WHERE date=(SELECT max(date) FROM v_positions) GROUP BY trader ORDER BY d DESC LIMIT 3"),
    ("Combien de dépassements de VaR par book ?", "SELECT book, count(*) FROM v_risque_book WHERE depassement_var GROUP BY book"),
    ("Évolution de la VaR du book TAUX_EUR sur les 30 derniers jours", "SELECT date, var99_1j_eur FROM v_risque_book WHERE book='TAUX_EUR' AND date>DATE '2026-10-30'-INTERVAL 30 DAY ORDER BY date"),
    ("P&L par mois du desk Change ?", "SELECT strftime(date,'%Y-%m') AS mois, sum(pnl_eur) FROM v_pnl WHERE desk='Change' GROUP BY 1 ORDER BY 1"),
    ("Quel est le cours de l'action Apple ?", None),
]


class Answer(BaseModel):
    sql: Optional[str] = None
    graphique: Optional[str] = None  # "ligne" | "barres" | None
    hypotheses: list[str] = []
    refus: Optional[str] = None


def system_prompt():
    views = "\n".join(
        f"- {v} ({spec['description']}): " + "; ".join(f"{c} {d[0]} = {d[1]}" for c, d in spec["columns"].items())
        for v, spec in CATALOG["views"].items())
    shots = "\n".join(
        f"Q: {q}\nR: " + json.dumps({"sql": s, "graphique": None, "hypotheses": [], "refus": None} if s else
                                     {"sql": None, "graphique": None, "hypotheses": [], "refus": "Hors du périmètre des données."}, ensure_ascii=False)
        for q, s in SHOTS)
    return f"""Tu traduis une question en français en une requête DuckDB (SELECT unique) sur ces vues, et rien d'autre:
{views}
Règles: la date de référence est {CATALOG['reference_date']} ("dernier jour" = max(date)); n'utilise jamais current_date ni now().
Seules ces vues existent. Les valeurs texte sont sensibles à la casse: desk ∈ 'Taux','Change'; book ∈ 'TAUX_EUR','TAUX_USD','FX_SPOT'; serie ∈ 'EUR_2Y','EUR_5Y','EUR_10Y','USD_2Y','USD_5Y','USD_10Y','EURUSD'. Renvoie seulement les colonnes demandées. "par X" ou "de chaque X" = GROUP BY X avec X dans le SELECT. "Brut" = somme des valeurs absolues. Sans période précisée, utilise toute la base (pas seulement le dernier jour). Un mois entier = du 1er au dernier jour du mois (octobre 2026 se termine le 31). Mois = BETWEEN premier et dernier jour. Si la question n'est pas répondable avec ces données, mets sql=null et explique dans refus.
Si tu as dû faire une hypothèse (ex: période non précisée), liste-la dans hypotheses.
Réponds par un seul objet JSON: {{"sql": ..., "graphique": "ligne"|"barres"|null, "hypotheses": [...], "refus": ...}}.
Exemples:
{shots}"""


def _chat(messages, client):
    r = client.chat(model=MODEL, messages=messages, format=Answer.model_json_schema(), think=False,
                    options={"temperature": 0, "num_ctx": 4096})
    return r["message"]["content"]


def propose(question, client=None):
    """Returns dict(answer=Answer|None, sql=validated sql|None, attempts=int, seconds=float, error=str|None).
    Not-answerable / invalid / still-rejected-after-repair all come back with sql=None (declared failure)."""
    import ollama
    client = client or ollama.Client()
    t0 = time.time()
    msgs = [{"role": "system", "content": system_prompt()}, {"role": "user", "content": question}]
    err = None
    for attempt in (1, 2):
        raw = _chat(msgs, client)
        try:
            ans = Answer.model_validate_json(raw)
            if ans.refus or not ans.sql:
                return dict(answer=ans, sql=None, attempts=attempt, seconds=time.time() - t0, error="refus")
            return dict(answer=ans, sql=check(ans.sql), attempts=attempt, seconds=time.time() - t0, error=None)
        except (ValidationError, Rejected) as e:
            err = str(e).splitlines()[0] if isinstance(e, ValidationError) else str(e)
            msgs += [{"role": "assistant", "content": raw},
                     {"role": "user", "content": f"Erreur: {err}. Corrige et renvoie le JSON complet."}]
    return dict(answer=None, sql=None, attempts=2, seconds=time.time() - t0, error=err)
