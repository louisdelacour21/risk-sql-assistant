"""Builds eval/test2.json: 60 fresh questions written AFTER the first test round and BEFORE the retrieval prompt ever saw them.
Test v1 (70) was used once, then burned for tuning; its pairs now feed the few-shot pool, so v2 is the number to quote.
sha256 in eval/TEST2_SHA256. No reference SQL may equal (normalised) any dev/test v1 SQL."""
import hashlib
import json
import sys
import sqlglot
sys.path.insert(0, "src")
from risksql import executor
from build_sets import q, mr, norm, DEV, TEST

LV = lambda t: f"(SELECT max(date) FROM {t})"
P = "v_positions"
RB = "v_risque_book"

T2 = [
    q("Donne-moi la VaR du book TAUX_USD au dernier jour", f"SELECT var99_1j_eur FROM {RB} WHERE book='TAUX_USD' AND date={LV(RB)}"),
    q("Quelle est l'ES du book TAUX_EUR le 15 septembre 2026 ?", f"SELECT es975_1j_eur FROM {RB} WHERE book='TAUX_EUR' AND date=DATE '2026-09-15'"),
    q("P&L total du trader Robert en octobre 2026 ?", f"SELECT sum(pnl_eur) FROM v_pnl WHERE trader='Robert' AND {mr('2026-10')}"),
    q("Quel est le P&L total du book FX_SPOT en juillet 2026 ?", f"SELECT sum(pnl_eur) FROM v_pnl WHERE book='FX_SPOT' AND {mr('2026-07')}"),
    q("Quel est le P&L total du desk Taux sur toute la période ?", "SELECT sum(pnl_eur) FROM v_pnl WHERE desk='Taux'"),
    q("Quels sont les 2 books avec la plus grande ES au dernier jour ?", f"SELECT book FROM {RB} WHERE date={LV(RB)} ORDER BY es975_1j_eur DESC LIMIT 2", True),
    q("Quels sont les 3 traders avec le plus grand notionnel brut au dernier jour ?", f"SELECT trader FROM {P} WHERE date={LV(P)} GROUP BY trader ORDER BY sum(abs(notionnel)) DESC LIMIT 3", True),
    q("Combien de jours le book TAUX_USD a-t-il dépassé 70 % de sa limite ?", "SELECT count(*) FROM v_limites WHERE book='TAUX_USD' AND utilisation_pct>70"),
    q("Combien de dépassements de VaR a eu le book TAUX_USD ?", f"SELECT count(*) FROM {RB} WHERE book='TAUX_USD' AND depassement_var"),
    q("Quels jours le book FX_SPOT a-t-il dépassé sa VaR ?", f"SELECT date FROM {RB} WHERE book='FX_SPOT' AND depassement_var"),
    q("Quel est le plus mauvais P&L journalier du book TAUX_EUR ?", f"SELECT min(pnl_eur) FROM {RB} WHERE book='TAUX_EUR'"),
    q("Quel est le meilleur P&L journalier du book TAUX_USD ?", f"SELECT max(pnl_eur) FROM {RB} WHERE book='TAUX_USD'"),
    q("Combien de positions a le trader Dubois au dernier jour ?", f"SELECT count(DISTINCT position_id) FROM {P} WHERE trader='Dubois' AND date={LV(P)}"),
    q("Combien de positions par desk au dernier jour ?", f"SELECT desk, count(*) FROM {P} WHERE date={LV(P)} GROUP BY desk"),
    q("Notionnel net total en EUR au dernier jour ?", f"SELECT sum(notionnel) FROM {P} WHERE devise='EUR' AND date={LV(P)}"),
    q("Notionnel brut total du book FX_SPOT au dernier jour ?", f"SELECT sum(abs(notionnel)) FROM {P} WHERE book='FX_SPOT' AND date={LV(P)}"),
    q("DV01 net total du book TAUX_EUR au dernier jour ?", f"SELECT sum(dv01_eur) FROM {P} WHERE book='TAUX_EUR' AND date={LV(P)}"),
    q("DV01 net par trader au dernier jour ?", f"SELECT trader, sum(dv01_eur) FROM {P} WHERE date={LV(P)} GROUP BY trader"),
    q("Quel trader a le plus gros DV01 absolu au dernier jour ?", f"SELECT trader FROM {P} WHERE date={LV(P)} GROUP BY trader ORDER BY sum(abs(dv01_eur)) DESC LIMIT 1", True),
    q("Quel desk a le meilleur P&L total ?", "SELECT desk FROM v_pnl GROUP BY desk ORDER BY sum(pnl_eur) DESC LIMIT 1", True),
    q("Quel book a le pire P&L total ?", "SELECT book FROM v_pnl GROUP BY book ORDER BY sum(pnl_eur) LIMIT 1", True),
    q("ES maximale par book ?", f"SELECT book, max(es975_1j_eur) FROM {RB} GROUP BY book"),
    q("VaR moyenne du book FX_SPOT ?", f"SELECT avg(var99_1j_eur) FROM {RB} WHERE book='FX_SPOT'"),
    q("Utilisation moyenne de la limite du book TAUX_USD ?", "SELECT avg(utilisation_pct) FROM v_limites WHERE book='TAUX_USD'"),
    q("Quelle est la limite du book FX_SPOT ?", "SELECT DISTINCT limite_eur FROM v_limites WHERE book='FX_SPOT'"),
    q("Quels books ont une ES moyenne supérieure à 500000 ?", f"SELECT book FROM {RB} GROUP BY book HAVING avg(es975_1j_eur)>500000"),
    q("Quels books ont déjà dépassé 75 % de leur limite ?", "SELECT DISTINCT book FROM v_limites WHERE utilisation_pct>75"),
    q("Quel jour l'ES du book TAUX_EUR a-t-elle été maximale ?", f"SELECT date FROM {RB} WHERE book='TAUX_EUR' ORDER BY es975_1j_eur DESC, date LIMIT 1", True),
    q("Quel jour le P&L du desk Change a-t-il été le meilleur ?", "SELECT date FROM v_pnl WHERE desk='Change' GROUP BY date ORDER BY sum(pnl_eur) DESC LIMIT 1", True),
    q("Quel jour le P&L du book TAUX_USD a-t-il été le plus mauvais ?", f"SELECT date FROM {RB} WHERE book='TAUX_USD' ORDER BY pnl_eur, date LIMIT 1", True),
    q("P&L du book TAUX_EUR par mois ?", "SELECT strftime(date,'%Y-%m') AS mois, sum(pnl_eur) FROM v_pnl WHERE book='TAUX_EUR' GROUP BY 1 ORDER BY 1", True, "chart"),
    q("Évolution de la VaR du book TAUX_USD sur les 45 derniers jours", f"SELECT date, var99_1j_eur FROM {RB} WHERE book='TAUX_USD' AND date>DATE '2026-10-30'-INTERVAL 45 DAY ORDER BY date", True, "chart"),
    q("Évolution du taux EUR 2Y sur les 60 derniers jours", "SELECT date, valeur FROM v_marche WHERE serie='EUR_2Y' AND date>DATE '2026-10-30'-INTERVAL 60 DAY ORDER BY date", True, "chart"),
    q("P&L cumulé du book FX_SPOT sur le mois de septembre 2026", f"SELECT date, sum(sum(pnl_eur)) OVER (ORDER BY date) AS cum FROM v_pnl WHERE book='FX_SPOT' AND {mr('2026-09')} GROUP BY date ORDER BY date", True, "chart"),
    q("Nombre de traders du desk Taux ?", f"SELECT count(DISTINCT trader) FROM {P} WHERE desk='Taux'"),
    q("Quels sont les traders du book FX_SPOT ?", f"SELECT DISTINCT trader FROM {P} WHERE book='FX_SPOT'"),
    q("Quels sont les instruments du book TAUX_USD ?", f"SELECT DISTINCT instrument FROM {P} WHERE book='TAUX_USD'"),
    q("Quelle est la première date de la base ?", f"SELECT min(date) FROM {P}"),
    q("Combien de jours de bourse en octobre 2026 ?", f"SELECT count(DISTINCT date) FROM v_pnl WHERE {mr('2026-10')}"),
    q("Taux USD 5Y au dernier jour ?", f"SELECT valeur FROM v_marche WHERE serie='USD_5Y' AND date={LV('v_marche')}"),
    q("Taux EUR 2Y moyen sur juillet 2026 ?", f"SELECT avg(valeur) FROM v_marche WHERE serie='EUR_2Y' AND {mr('2026-07')}"),
    q("EURUSD moyen sur toute la période ?", "SELECT avg(valeur) FROM v_marche WHERE serie='EURUSD'"),
    q("Taux USD 10Y le plus haut de la période ?", "SELECT max(valeur) FROM v_marche WHERE serie='USD_10Y'"),
    q("Pente 10Y-2Y USD le 15 octobre 2026 ?", "SELECT (SELECT valeur FROM v_marche WHERE serie='USD_10Y' AND date=DATE '2026-10-15')-(SELECT valeur FROM v_marche WHERE serie='USD_2Y' AND date=DATE '2026-10-15')"),
    q("Pente 5Y-2Y EUR au dernier jour ?", f"SELECT (SELECT valeur FROM v_marche WHERE serie='EUR_5Y' AND date={LV('v_marche')})-(SELECT valeur FROM v_marche WHERE serie='EUR_2Y' AND date={LV('v_marche')})"),
    q("Variation de l'EURUSD entre le 1er septembre et le 30 septembre 2026", "SELECT (SELECT valeur FROM v_marche WHERE serie='EURUSD' AND date=DATE '2026-09-30')-(SELECT valeur FROM v_marche WHERE serie='EURUSD' AND date=DATE '2026-09-01')"),
    q("Écart de P&L entre le book TAUX_EUR et le book TAUX_USD sur toute la période", "SELECT (SELECT sum(pnl_eur) FROM v_pnl WHERE book='TAUX_EUR')-(SELECT sum(pnl_eur) FROM v_pnl WHERE book='TAUX_USD')"),
    q("Part du P&L total due au desk Change", "SELECT (SELECT sum(pnl_eur) FROM v_pnl WHERE desk='Change')/(SELECT sum(pnl_eur) FROM v_pnl)"),
    q("Écart-type de la VaR du book TAUX_EUR ?", f"SELECT stddev_samp(var99_1j_eur) FROM {RB} WHERE book='TAUX_EUR'"),
    q("Médiane de l'ES du book FX_SPOT ?", f"SELECT median(es975_1j_eur) FROM {RB} WHERE book='FX_SPOT'"),
    q("Combien de jours le P&L du book TAUX_USD a-t-il été positif ?", f"SELECT count(*) FROM {RB} WHERE book='TAUX_USD' AND pnl_eur>0"),
    q("Classe les traders par P&L total croissant", "SELECT trader, sum(pnl_eur) FROM v_pnl GROUP BY trader ORDER BY sum(pnl_eur)", True),
    q("Classe les books par VaR moyenne décroissante", f"SELECT book, avg(var99_1j_eur) FROM {RB} GROUP BY book ORDER BY avg(var99_1j_eur) DESC", True),
    q("VaR du book FX_SPOT le 2 octobre 2026 ?", f"SELECT var99_1j_eur FROM {RB} WHERE book='FX_SPOT' AND date=DATE '2026-10-02'"),
    q("Utilisation de limite de TAUX_USD le 30 septembre 2026 ?", "SELECT utilisation_pct FROM v_limites WHERE book='TAUX_USD' AND date=DATE '2026-09-30'"),
    q("Delta FX total du book FX_SPOT au dernier jour ?", f"SELECT sum(delta_fx_eur) FROM {P} WHERE book='FX_SPOT' AND date={LV(P)}"),
    q("Delta FX net par devise au dernier jour ?", f"SELECT devise, sum(delta_fx_eur) FROM {P} WHERE date={LV(P)} GROUP BY devise"),
    q("ES moyenne en août 2026 par book", f"SELECT book, avg(es975_1j_eur) FROM {RB} WHERE {mr('2026-08')} GROUP BY book"),
    q("Nombre de positions long (notionnel positif) au dernier jour ?", f"SELECT count(*) FROM {P} WHERE notionnel>0 AND date={LV(P)}"),
    q("Notionnel du plus gros long au dernier jour ?", f"SELECT max(notionnel) FROM {P} WHERE date={LV(P)}"),
]
assert len(T2) == 60, len(T2)


con = executor.connect("data/risk.duckdb")
seen = {norm(x["sql"]) for x in DEV + TEST}
items = []
for i, it in enumerate(T2, 1):
    _, df = executor.run(con, it["sql"])
    assert len(df) > 0, (i, it["question"], "empty result")
    assert norm(it["sql"]) not in seen, (i, it["question"], "same SQL as dev/test v1")
    items.append(dict(id=f"U{i:02d}", question=it["question"], reference_sql=it["sql"], ordered=it["ordered"], kind=it["kind"]))
assert len({x["question"] for x in items} & {x["question"] for x in DEV + TEST}) == 0
json.dump(items, open("eval/test2.json", "w", encoding="utf8"), ensure_ascii=False, indent=1)
open("eval/TEST2_SHA256", "w").write(hashlib.sha256(open("eval/test2.json", "rb").read()).hexdigest() + "\n")
print(len(items), "questions written")
