"""Builds eval/dev.json (30, used to write prompts/templates) and eval/test.json (70, frozen, sha256 in eval/TEST_SHA256).
Every reference SQL is run through the guard and the executor; test must not share a normalised SQL with dev."""
import calendar
import hashlib
import json
import sys
import sqlglot
sys.path.insert(0, "src")
from risksql import executor

LAST = "(SELECT max(date) FROM v_positions)"


def q(question, sql, ordered=False, kind="select"):
    return dict(question=question, sql=sql, ordered=ordered, kind=kind)


def mr(m):
    y, mo = map(int, m.split("-"))
    return f"date BETWEEN DATE '{m}-01' AND DATE '{m}-{calendar.monthrange(y, mo)[1]}'"


DEV = [
    q("Quelle est la VaR du book TAUX_EUR au dernier jour ?", "SELECT var99_1j_eur FROM v_risque_book WHERE book='TAUX_EUR' AND date=(SELECT max(date) FROM v_risque_book)"),
    q("Quel est le P&L total du desk Taux en octobre 2026 ?", "SELECT sum(pnl_eur) FROM v_pnl WHERE desk='Taux' AND date>=DATE '2026-10-01'"),
    q("Quels sont les 3 traders avec le plus grand DV01 absolu au dernier jour ?", f"SELECT trader, sum(abs(dv01_eur)) AS d FROM v_positions WHERE date={LAST} GROUP BY trader ORDER BY d DESC LIMIT 3", True),
    q("Combien de jours le book FX_SPOT a-t-il dépassé 80 % de sa limite ?", "SELECT count(*) FROM v_limites WHERE book='FX_SPOT' AND utilisation_pct>80"),
    q("Combien de dépassements de VaR par book ?", "SELECT book, count(*) FROM v_risque_book WHERE depassement_var GROUP BY book"),
    q("Quel est le taux EUR 10Y au dernier jour ?", "SELECT valeur FROM v_marche WHERE serie='EUR_10Y' AND date=(SELECT max(date) FROM v_marche)"),
    q("P&L total par book ?", "SELECT book, sum(pnl_eur) FROM v_pnl GROUP BY book"),
    q("Quel est le pire P&L journalier du book TAUX_USD ?", "SELECT min(pnl_eur) FROM v_risque_book WHERE book='TAUX_USD'"),
    q("Combien de positions a le trader Martin au dernier jour ?", f"SELECT count(DISTINCT position_id) FROM v_positions WHERE trader='Martin' AND date={LAST}"),
    q("Quelle est la VaR moyenne par book ?", "SELECT book, avg(var99_1j_eur) FROM v_risque_book GROUP BY book"),
    q("Notionnel brut total en USD au dernier jour ?", f"SELECT sum(abs(notionnel)) FROM v_positions WHERE devise='USD' AND date={LAST}"),
    q("Quel jour la VaR du book FX_SPOT a-t-elle été maximale ?", "SELECT date FROM v_risque_book WHERE book='FX_SPOT' ORDER BY var99_1j_eur DESC LIMIT 1", True),
    q("Utilisation moyenne de la limite par book ?", "SELECT book, avg(utilisation_pct) FROM v_limites GROUP BY book"),
    q("P&L total du trader Dubois ?", "SELECT sum(pnl_eur) FROM v_pnl WHERE trader='Dubois'"),
    q("Quelle est la valeur de l'EURUSD le 15 septembre 2026 ?", "SELECT valeur FROM v_marche WHERE serie='EURUSD' AND date=DATE '2026-09-15'"),
    q("Limite en euros de chaque book ?", "SELECT DISTINCT book, limite_eur FROM v_limites"),
    q("Delta FX total au dernier jour ?", f"SELECT sum(delta_fx_eur) FROM v_positions WHERE date={LAST}"),
    q("Quels books ont un ES moyen supérieur à 300000 ?", "SELECT book FROM v_risque_book GROUP BY book HAVING avg(es975_1j_eur)>300000"),
    q("P&L par mois du desk Change ?", "SELECT strftime(date,'%Y-%m') AS mois, sum(pnl_eur) FROM v_pnl WHERE desk='Change' GROUP BY 1 ORDER BY 1", True, "chart"),
    q("Évolution de la VaR du book TAUX_EUR sur les 30 derniers jours", "SELECT date, var99_1j_eur FROM v_risque_book WHERE book='TAUX_EUR' AND date>DATE '2026-10-30'-INTERVAL 30 DAY ORDER BY date", True, "chart"),
    q("Combien de traders par desk ?", "SELECT desk, count(DISTINCT trader) FROM v_positions GROUP BY desk"),
    q("Le jour où le P&L du book TAUX_EUR a été le plus mauvais, quelle était sa VaR ?", "SELECT date, pnl_eur, var99_1j_eur FROM v_risque_book WHERE book='TAUX_EUR' ORDER BY pnl_eur LIMIT 1", True),
    q("Top 5 des positions par notionnel absolu au dernier jour", f"SELECT position_id, abs(notionnel) AS n FROM v_positions WHERE date={LAST} ORDER BY n DESC, position_id LIMIT 5", True),
    q("Nombre de jours de bourse dans la base ?", "SELECT count(DISTINCT date) FROM v_pnl"),
    q("Taux USD 2Y moyen sur septembre 2026 ?", "SELECT avg(valeur) FROM v_marche WHERE serie='USD_2Y' AND date BETWEEN DATE '2026-09-01' AND DATE '2026-09-30'"),
    q("Quels sont les books du desk Taux ?", "SELECT DISTINCT book FROM v_positions WHERE desk='Taux'"),
    q("Quel book a la plus forte utilisation de limite au dernier jour ?", "SELECT book FROM v_limites WHERE date=(SELECT max(date) FROM v_limites) ORDER BY utilisation_pct DESC LIMIT 1", True),
    q("Écart de P&L entre le trader Robert et le trader Petit sur toute la période", "SELECT (SELECT sum(pnl_eur) FROM v_pnl WHERE trader='Robert')-(SELECT sum(pnl_eur) FROM v_pnl WHERE trader='Petit')"),
    q("Quel est le P&L du desk Taux le jour le plus récent ?", "SELECT sum(pnl_eur) FROM v_pnl WHERE desk='Taux' AND date=(SELECT max(date) FROM v_pnl)"),
    q("Pente 10Y-2Y EUR au dernier jour ?", "SELECT (SELECT valeur FROM v_marche WHERE serie='EUR_10Y' AND date=(SELECT max(date) FROM v_marche))-(SELECT valeur FROM v_marche WHERE serie='EUR_2Y' AND date=(SELECT max(date) FROM v_marche))"),
]

TEST = [
    q("Quelle est la VaR du book FX_SPOT au dernier jour ?", "SELECT var99_1j_eur FROM v_risque_book WHERE book='FX_SPOT' AND date=(SELECT max(date) FROM v_risque_book)"),
    q("Quelle est l'ES du book TAUX_USD au dernier jour ?", "SELECT es975_1j_eur FROM v_risque_book WHERE book='TAUX_USD' AND date=(SELECT max(date) FROM v_risque_book)"),
    q("Quel est le P&L total du desk Change en septembre 2026 ?", f"SELECT sum(pnl_eur) FROM v_pnl WHERE desk='Change' AND {mr('2026-09')}"),
    q("Quel est le P&L total du book TAUX_USD en août 2026 ?", f"SELECT sum(pnl_eur) FROM v_pnl WHERE book='TAUX_USD' AND {mr('2026-08')}"),
    q("Quels sont les 3 books avec la plus grande VaR au dernier jour ?", "SELECT book, var99_1j_eur FROM v_risque_book WHERE date=(SELECT max(date) FROM v_risque_book) ORDER BY var99_1j_eur DESC LIMIT 3", True),
    q("Quels sont les 2 traders avec le plus grand delta FX absolu au dernier jour ?", f"SELECT trader, sum(abs(delta_fx_eur)) AS d FROM v_positions WHERE date={LAST} GROUP BY trader ORDER BY d DESC LIMIT 2", True),
    q("Combien de jours le book TAUX_EUR a-t-il dépassé 80 % de sa limite ?", "SELECT count(*) FROM v_limites WHERE book='TAUX_EUR' AND utilisation_pct>80"),
    q("Combien de jours le book TAUX_USD a-t-il dépassé 90 % de sa limite ?", "SELECT count(*) FROM v_limites WHERE book='TAUX_USD' AND utilisation_pct>90"),
    q("Combien de dépassements de VaR a eu le book FX_SPOT ?", "SELECT count(*) FROM v_risque_book WHERE book='FX_SPOT' AND depassement_var"),
    q("Combien de dépassements de VaR au total ?", "SELECT count(*) FROM v_risque_book WHERE depassement_var"),
    q("Quels jours le book TAUX_EUR a-t-il dépassé sa VaR ?", "SELECT date FROM v_risque_book WHERE book='TAUX_EUR' AND depassement_var ORDER BY date", True),
    q("Quel est le meilleur P&L journalier du book FX_SPOT ?", "SELECT max(pnl_eur) FROM v_risque_book WHERE book='FX_SPOT'"),
    q("Quel est le pire P&L journalier tous books confondus ?", "SELECT min(pnl_eur) FROM v_risque_book"),
    q("Combien de positions a le trader Thomas au dernier jour ?", f"SELECT count(DISTINCT position_id) FROM v_positions WHERE trader='Thomas' AND date={LAST}"),
    q("Combien de positions par book au dernier jour ?", f"SELECT book, count(*) FROM v_positions WHERE date={LAST} GROUP BY book"),
    q("Notionnel net total par devise au dernier jour ?", f"SELECT devise, sum(notionnel) FROM v_positions WHERE date={LAST} GROUP BY devise"),
    q("Notionnel brut total du book TAUX_EUR au dernier jour ?", f"SELECT sum(abs(notionnel)) FROM v_positions WHERE book='TAUX_EUR' AND date={LAST}"),
    q("DV01 net total du book TAUX_USD au dernier jour ?", f"SELECT sum(dv01_eur) FROM v_positions WHERE book='TAUX_USD' AND date={LAST}"),
    q("Quel trader a le plus gros P&L total ?", "SELECT trader FROM v_pnl GROUP BY trader ORDER BY sum(pnl_eur) DESC LIMIT 1", True),
    q("Quel trader a le plus mauvais P&L total ?", "SELECT trader FROM v_pnl GROUP BY trader ORDER BY sum(pnl_eur) LIMIT 1", True),
    q("P&L total par trader ?", "SELECT trader, sum(pnl_eur) FROM v_pnl GROUP BY trader"),
    q("P&L total par desk ?", "SELECT desk, sum(pnl_eur) FROM v_pnl GROUP BY desk"),
    q("ES moyen par book ?", "SELECT book, avg(es975_1j_eur) FROM v_risque_book GROUP BY book"),
    q("VaR maximale par book ?", "SELECT book, max(var99_1j_eur) FROM v_risque_book GROUP BY book"),
    q("Utilisation maximale de la limite par book ?", "SELECT book, max(utilisation_pct) FROM v_limites GROUP BY book"),
    q("Quelle est l'utilisation de la limite du book FX_SPOT au dernier jour ?", "SELECT utilisation_pct FROM v_limites WHERE book='FX_SPOT' AND date=(SELECT max(date) FROM v_limites)"),
    q("Quelle est la limite du book TAUX_USD ?", "SELECT DISTINCT limite_eur FROM v_limites WHERE book='TAUX_USD'"),
    q("Quels books ont une VaR moyenne supérieure à 1 million ?", "SELECT book FROM v_risque_book GROUP BY book HAVING avg(var99_1j_eur)>1000000"),
    q("Quels books ont déjà dépassé 85 % de leur limite ?", "SELECT DISTINCT book FROM v_limites WHERE utilisation_pct>85"),
    q("Quel jour la VaR du book TAUX_USD a-t-elle été minimale ?", "SELECT date FROM v_risque_book WHERE book='TAUX_USD' ORDER BY var99_1j_eur, date LIMIT 1", True),
    q("Quel jour le P&L du desk Taux a-t-il été le plus mauvais ?", "SELECT date FROM v_pnl WHERE desk='Taux' GROUP BY date ORDER BY sum(pnl_eur) LIMIT 1", True),
    q("P&L du book FX_SPOT par mois ?", "SELECT strftime(date,'%Y-%m') AS mois, sum(pnl_eur) FROM v_pnl WHERE book='FX_SPOT' GROUP BY 1 ORDER BY 1", True, "chart"),
    q("Évolution de la VaR du book FX_SPOT sur les 60 derniers jours", "SELECT date, var99_1j_eur FROM v_risque_book WHERE book='FX_SPOT' AND date>DATE '2026-10-30'-INTERVAL 60 DAY ORDER BY date", True, "chart"),
    q("Évolution du taux USD 10Y sur les 90 derniers jours", "SELECT date, valeur FROM v_marche WHERE serie='USD_10Y' AND date>DATE '2026-10-30'-INTERVAL 90 DAY ORDER BY date", True, "chart"),
    q("P&L cumulé du desk Taux sur le mois d'octobre 2026", "SELECT date, sum(sum(pnl_eur)) OVER (ORDER BY date) AS cum FROM v_pnl WHERE desk='Taux' AND date>=DATE '2026-10-01' GROUP BY date ORDER BY date", True, "chart"),
    q("Nombre de traders par book ?", "SELECT book, count(DISTINCT trader) FROM v_positions GROUP BY book"),
    q("Quels sont les books du desk Change ?", "SELECT DISTINCT book FROM v_positions WHERE desk='Change'"),
    q("Quels traders travaillent sur le book TAUX_USD ?", "SELECT DISTINCT trader FROM v_positions WHERE book='TAUX_USD'"),
    q("Quelle est la date la plus récente de la base ?", "SELECT max(date) FROM v_pnl"),
    q("Combien de positions distinctes dans la base ?", "SELECT count(DISTINCT position_id) FROM v_positions"),
    q("Quels sont les instruments du book TAUX_EUR ?", "SELECT DISTINCT instrument FROM v_positions WHERE book='TAUX_EUR'"),
    q("EURUSD le plus haut de la période ?", "SELECT max(valeur) FROM v_marche WHERE serie='EURUSD'"),
    q("EURUSD le plus bas de la période ?", "SELECT min(valeur) FROM v_marche WHERE serie='EURUSD'"),
    q("Taux EUR 5Y au dernier jour ?", "SELECT valeur FROM v_marche WHERE serie='EUR_5Y' AND date=(SELECT max(date) FROM v_marche)"),
    q("Taux USD 10Y moyen sur août 2026 ?", f"SELECT avg(valeur) FROM v_marche WHERE serie='USD_10Y' AND {mr('2026-08')}"),
    q("Pente 10Y-2Y USD au dernier jour ?", "SELECT (SELECT valeur FROM v_marche WHERE serie='USD_10Y' AND date=(SELECT max(date) FROM v_marche))-(SELECT valeur FROM v_marche WHERE serie='USD_2Y' AND date=(SELECT max(date) FROM v_marche))"),
    q("Variation du taux EUR 10Y entre le 1er et le 30 octobre 2026", "SELECT (SELECT valeur FROM v_marche WHERE serie='EUR_10Y' AND date=DATE '2026-10-30')-(SELECT valeur FROM v_marche WHERE serie='EUR_10Y' AND date=DATE '2026-10-01')"),
    q("Écart de P&L entre le desk Taux et le desk Change sur toute la période", "SELECT (SELECT sum(pnl_eur) FROM v_pnl WHERE desk='Taux')-(SELECT sum(pnl_eur) FROM v_pnl WHERE desk='Change')"),
    q("Part du P&L total due au trader Martin", "SELECT (SELECT sum(pnl_eur) FROM v_pnl WHERE trader='Martin')/(SELECT sum(pnl_eur) FROM v_pnl)"),
    q("P&L moyen journalier du book TAUX_EUR ?", "SELECT avg(pnl_eur) FROM v_risque_book WHERE book='TAUX_EUR'"),
    q("Écart-type du P&L journalier du book FX_SPOT ?", "SELECT stddev_samp(pnl_eur) FROM v_risque_book WHERE book='FX_SPOT'"),
    q("Médiane de la VaR du book TAUX_USD ?", "SELECT median(var99_1j_eur) FROM v_risque_book WHERE book='TAUX_USD'"),
    q("Combien de jours le P&L du book TAUX_EUR a-t-il été négatif ?", "SELECT count(*) FROM v_risque_book WHERE book='TAUX_EUR' AND pnl_eur<0"),
    q("Combien de jours le P&L total de la banque a-t-il été négatif ?", "SELECT count(*) FROM (SELECT date FROM v_pnl GROUP BY date HAVING sum(pnl_eur)<0)"),
    q("Classe les books par P&L total décroissant", "SELECT book, sum(pnl_eur) AS p FROM v_pnl GROUP BY book ORDER BY p DESC", True),
    q("Classe les traders par notionnel brut au dernier jour", f"SELECT trader, sum(abs(notionnel)) AS n FROM v_positions WHERE date={LAST} GROUP BY trader ORDER BY n DESC", True),
    q("Le jour du pire P&L de FX_SPOT, quelle était sa VaR ?", "SELECT date, pnl_eur, var99_1j_eur FROM v_risque_book WHERE book='FX_SPOT' ORDER BY pnl_eur LIMIT 1", True),
    q("Quel est le P&L du trader Bernard en juillet 2026 ?", f"SELECT sum(pnl_eur) FROM v_pnl WHERE trader='Bernard' AND {mr('2026-07')}"),
    q("Quel est le P&L du trader Petit le dernier jour ?", "SELECT sum(pnl_eur) FROM v_pnl WHERE trader='Petit' AND date=(SELECT max(date) FROM v_pnl)"),
    q("VaR du book TAUX_EUR le 30 septembre 2026 ?", "SELECT var99_1j_eur FROM v_risque_book WHERE book='TAUX_EUR' AND date=DATE '2026-09-30'"),
    q("ES du book FX_SPOT le 15 octobre 2026 ?", "SELECT es975_1j_eur FROM v_risque_book WHERE book='FX_SPOT' AND date=DATE '2026-10-15'"),
    q("Utilisation de limite de TAUX_EUR le 1er octobre 2026 ?", "SELECT utilisation_pct FROM v_limites WHERE book='TAUX_EUR' AND date=DATE '2026-10-01'"),
    q("Valeur de l'EURUSD le 2 septembre 2026 ?", "SELECT valeur FROM v_marche WHERE serie='EURUSD' AND date=DATE '2026-09-02'"),
    q("Delta FX du book FX_SPOT par trader au dernier jour", f"SELECT trader, sum(delta_fx_eur) FROM v_positions WHERE book='FX_SPOT' AND date={LAST} GROUP BY trader"),
    q("DV01 absolu par instrument du book TAUX_EUR au dernier jour", f"SELECT instrument, sum(abs(dv01_eur)) FROM v_positions WHERE book='TAUX_EUR' AND date={LAST} GROUP BY instrument"),
    q("Combien de jours VaR du book TAUX_EUR au-dessus de 250000 ?", "SELECT count(*) FROM v_risque_book WHERE book='TAUX_EUR' AND var99_1j_eur>250000"),
    q("Utilisation de limite moyenne en octobre 2026 par book", f"SELECT book, avg(utilisation_pct) FROM v_limites WHERE {mr('2026-10')} GROUP BY book"),
    q("VaR moyenne en septembre 2026 par book", f"SELECT book, avg(var99_1j_eur) FROM v_risque_book WHERE {mr('2026-09')} GROUP BY book"),
    q("Nombre de positions short (notionnel négatif) au dernier jour", f"SELECT count(*) FROM v_positions WHERE notionnel<0 AND date={LAST}"),
    q("Notionnel du plus gros short au dernier jour", f"SELECT min(notionnel) FROM v_positions WHERE date={LAST}"),
]
assert len(DEV) == 30 and len(TEST) == 70, (len(DEV), len(TEST))


def norm(sql):
    return sqlglot.parse_one(sql, read="duckdb").sql(dialect="duckdb", normalize=True).lower()


def finish(items, prefix):
    con = executor.connect("data/risk.duckdb")
    out = []
    for i, it in enumerate(items, 1):
        _, df = executor.run(con, it["sql"])
        assert len(df) > 0, (prefix, i, it["question"], "empty result")
        out.append(dict(id=f"{prefix}{i:02d}", question=it["question"], reference_sql=it["sql"], ordered=it["ordered"], kind=it["kind"]))
    return out


if __name__ == "__main__":
    dev, test = finish(DEV, "D"), finish(TEST, "T")
    nd = {norm(x["reference_sql"]) for x in dev}
    leak = [x["id"] for x in test if norm(x["reference_sql"]) in nd]
    assert not leak, f"test/dev share reference SQL: {leak}"
    assert len({x["question"] for x in dev + test}) == 100, "duplicate question"
    json.dump(dev, open("eval/dev.json", "w", encoding="utf8"), ensure_ascii=False, indent=1)
    json.dump(test, open("eval/test.json", "w", encoding="utf8"), ensure_ascii=False, indent=1)
    open("eval/TEST_SHA256", "w").write(hashlib.sha256(open("eval/test.json", "rb").read()).hexdigest() + "\n")
    print("ok", len(dev), len(test))
