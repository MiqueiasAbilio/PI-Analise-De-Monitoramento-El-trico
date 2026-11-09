from __future__ import annotations

import math
import sqlite3
from datetime import date, datetime, time, timedelta
from pathlib import Path

from flask import Flask, flash, redirect, render_template, request, url_for


DEFAULT_SETTINGS = {
    "tarifa": "0.95",
    "manha": "20",
    "tarde": "30",
    "noite": "50",
}
PERIOD_HOURS = {"manha": 6, "tarde": 6, "noite": 12}
PERIOD_LABELS = {"manha": "Manha", "tarde": "Tarde", "noite": "Noite"}


def create_app(database_path: str | Path | None = None) -> Flask:
    app = Flask(__name__)
    app.secret_key = "controle-energia-local"
    app.config["DATABASE"] = Path(database_path or Path(__file__).parent / "data" / "energia.db")
    initialize_database(app.config["DATABASE"])

    @app.template_filter("br")
    def format_brazilian_number(value):
        return f"{float(value):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    @app.get("/")
    def dashboard():
        today = date.today()
        period = request.args.get("periodo", "30d")
        start_day, end_day = selected_dates(period, today)
        try:
            custom_start = request.args.get("inicio")
            custom_end = request.args.get("fim")
            if period == "custom":
                start_day = date.fromisoformat(custom_start) if custom_start else today.replace(day=1)
                end_day = date.fromisoformat(custom_end) if custom_end else today
                if start_day > end_day:
                    raise ValueError
        except ValueError:
            flash("O intervalo de datas informado nao e valido.", "error")
            period = "30d"
            start_day, end_day = selected_dates(period, today)

        circuit_filter = request.args.get("circuito", "")
        db = connect_db(app.config["DATABASE"])
        try:
            circuits = db.execute("SELECT id, name FROM circuits ORDER BY name COLLATE NOCASE").fetchall()
            settings = read_settings(db)
            if circuit_filter and not any(str(row["id"]) == circuit_filter for row in circuits):
                circuit_filter = ""
            window_start = datetime.combine(start_day, time.min)
            window_end = datetime.combine(end_day + timedelta(days=1), time.min)
            readings = db.execute(
                """SELECT r.*, c.name AS circuit_name FROM readings r
                   LEFT JOIN circuits c ON c.id = r.circuit_id
                   WHERE r.end_at > ? AND r.start_at < ?
                   ORDER BY r.start_at DESC""",
                (window_start.isoformat(timespec="minutes"), window_end.isoformat(timespec="minutes")),
            ).fetchall()
            if circuit_filter:
                readings = [row for row in readings if row["circuit_id"] is None or str(row["circuit_id"]) == circuit_filter]
            network_rows = [row for row in readings if row["source"] == "rede"]
            circuit_rows = [row for row in readings if row["source"] == "circuito"]
            analyses = {
                "rede": analyze(network_rows, window_start, window_end, settings),
                "circuito": analyze(circuit_rows, window_start, window_end, settings),
            }
            readings = readings[:100]
            total_kwh = sum(item["total_kwh"] for item in analyses.values())
            total_cost = total_kwh * float(settings["tarifa"])
            selected_circuit_name = next(
                (row["name"] for row in circuits if str(row["id"]) == circuit_filter),
                "Todos os circuitos",
            )
        finally:
            db.close()

        return render_template(
            "dashboard.html",
            circuits=circuits,
            readings=readings,
            analyses=analyses,
            settings=settings,
            period=period,
            start_day=start_day.isoformat(),
            end_day=end_day.isoformat(),
            circuit_filter=circuit_filter,
            selected_circuit_name=selected_circuit_name,
            total_kwh=total_kwh,
            total_cost=total_cost,
            period_labels=PERIOD_LABELS,
        )

    @app.post("/leituras")
    def add_reading():
        source = request.form.get("source", "")
        try:
            start_at = datetime.fromisoformat(request.form["start_at"])
            end_at = datetime.fromisoformat(request.form["end_at"])
            kwh = float(request.form["kwh"])
            circuit_id = int(request.form["circuit_id"]) if source == "circuito" else None
            if source not in {"rede", "circuito"} or start_at >= end_at or not math.isfinite(kwh) or kwh <= 0:
                raise ValueError
            db = connect_db(app.config["DATABASE"])
            try:
                if circuit_id is not None and not db.execute("SELECT 1 FROM circuits WHERE id = ?", (circuit_id,)).fetchone():
                    raise ValueError
                db.execute(
                    "INSERT INTO readings (source, circuit_id, start_at, end_at, kwh) VALUES (?, ?, ?, ?, ?)",
                    (source, circuit_id, start_at.isoformat(timespec="minutes"), end_at.isoformat(timespec="minutes"), kwh),
                )
                db.commit()
            finally:
                db.close()
            flash("Leitura registrada.", "success")
        except (KeyError, TypeError, ValueError):
            flash("Confira as datas, o circuito e o consumo informado.", "error")
        return redirect(url_for("dashboard"))

    @app.post("/circuitos")
    def add_circuit():
        name = request.form.get("name", "").strip()
        if not name or len(name) > 60:
            flash("Informe um nome de circuito com ate 60 caracteres.", "error")
        else:
            db = connect_db(app.config["DATABASE"])
            try:
                db.execute("INSERT INTO circuits (name) VALUES (?)", (name,))
                db.commit()
                flash("Circuito criado.", "success")
            except sqlite3.IntegrityError:
                flash("Ja existe um circuito com esse nome.", "error")
            finally:
                db.close()
        return redirect(url_for("dashboard") + "#circuitos")

    @app.post("/circuitos/<int:circuit_id>/editar")
    def edit_circuit(circuit_id: int):
        name = request.form.get("name", "").strip()
        if not name or len(name) > 60:
            flash("Informe um nome de circuito com ate 60 caracteres.", "error")
        else:
            db = connect_db(app.config["DATABASE"])
            try:
                db.execute("UPDATE circuits SET name = ? WHERE id = ?", (name, circuit_id))
                db.commit()
                flash("Circuito atualizado.", "success")
            except sqlite3.IntegrityError:
                flash("Ja existe um circuito com esse nome.", "error")
            finally:
                db.close()
        return redirect(url_for("dashboard") + "#circuitos")

    @app.post("/circuitos/<int:circuit_id>/excluir")
    def delete_circuit(circuit_id: int):
        db = connect_db(app.config["DATABASE"])
        try:
            has_readings = db.execute("SELECT 1 FROM readings WHERE circuit_id = ? LIMIT 1", (circuit_id,)).fetchone()
            if has_readings:
                flash("Este circuito possui leituras. Exclua as leituras antes de remove-lo.", "error")
            else:
                db.execute("DELETE FROM circuits WHERE id = ?", (circuit_id,))
                db.commit()
                flash("Circuito removido.", "success")
        finally:
            db.close()
        return redirect(url_for("dashboard") + "#circuitos")

    @app.post("/leituras/<int:reading_id>/excluir")
    def delete_reading(reading_id: int):
        db = connect_db(app.config["DATABASE"])
        try:
            db.execute("DELETE FROM readings WHERE id = ?", (reading_id,))
            db.commit()
        finally:
            db.close()
        flash("Leitura removida.", "success")
        return redirect(url_for("dashboard"))

    @app.post("/configuracoes")
    def update_settings():
        try:
            values = {
                "tarifa": float(request.form["tarifa"]),
                "manha": int(request.form["manha"]),
                "tarde": int(request.form["tarde"]),
                "noite": int(request.form["noite"]),
            }
            if not math.isfinite(values["tarifa"]) or values["tarifa"] <= 0 or any(values[key] < 0 for key in PERIOD_HOURS) or sum(values[key] for key in PERIOD_HOURS) != 100:
                raise ValueError
            db = connect_db(app.config["DATABASE"])
            try:
                for key, value in values.items():
                    db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
                db.commit()
            finally:
                db.close()
            flash("Tarifa e perfil de consumo atualizados.", "success")
        except (KeyError, TypeError, ValueError):
            flash("A tarifa deve ser positiva e as faixas precisam somar 100%.", "error")
        return redirect(url_for("dashboard") + "#configuracoes")

    return app


def initialize_database(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA foreign_keys = ON")
        db.executescript(
            """CREATE TABLE IF NOT EXISTS circuits (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   name TEXT NOT NULL COLLATE NOCASE UNIQUE
               );
               CREATE TABLE IF NOT EXISTS readings (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   source TEXT NOT NULL CHECK (source IN ('rede', 'circuito')),
                   circuit_id INTEGER REFERENCES circuits(id),
                   start_at TEXT NOT NULL,
                   end_at TEXT NOT NULL,
                   kwh REAL NOT NULL CHECK (kwh > 0),
                   CHECK (end_at > start_at),
                   CHECK ((source = 'rede' AND circuit_id IS NULL) OR (source = 'circuito' AND circuit_id IS NOT NULL))
               );
               CREATE TABLE IF NOT EXISTS settings (
                   key TEXT PRIMARY KEY,
                   value TEXT NOT NULL
               );"""
        )
        for key, value in DEFAULT_SETTINGS.items():
            db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value))


def connect_db(path: Path) -> sqlite3.Connection:
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def read_settings(db: sqlite3.Connection) -> dict[str, str]:
    settings = DEFAULT_SETTINGS.copy()
    settings.update({row["key"]: row["value"] for row in db.execute("SELECT key, value FROM settings")})
    return settings


def selected_dates(period: str, today: date) -> tuple[date, date]:
    if period == "7d":
        return today - timedelta(days=6), today
    if period == "month":
        return today.replace(day=1), today
    if period == "custom":
        return today.replace(day=1), today
    return today - timedelta(days=29), today


def period_for_hour(hour: int) -> str:
    if 6 <= hour < 12:
        return "manha"
    if 12 <= hour < 18:
        return "tarde"
    return "noite"


def weighted_hours(start: datetime, end: datetime, settings: dict[str, str]) -> dict[str, float]:
    weights = {key: 0.0 for key in PERIOD_HOURS}
    cursor = start
    while cursor < end:
        next_hour = cursor.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
        segment_end = min(next_hour, end)
        period = period_for_hour(cursor.hour)
        share = float(settings[period]) / 100
        weights[period] += (segment_end - cursor).total_seconds() / 3600 * share / PERIOD_HOURS[period]
        cursor = segment_end
    return weights


def allocate_energy(
    start: datetime,
    end: datetime,
    kwh: float,
    settings: dict[str, str],
    clip_start: datetime,
    clip_end: datetime,
) -> dict[str, float]:
    full_weights = weighted_hours(start, end, settings)
    denominator = sum(full_weights.values())
    if denominator <= 0:
        uniform_profile = {"manha": "25", "tarde": "25", "noite": "50"}
        uniform_full = weighted_hours(start, end, uniform_profile)
        uniform_denominator = sum(uniform_full.values())
        if uniform_denominator <= 0:
            return {key: 0.0 for key in PERIOD_HOURS}
        clipped_start = max(start, clip_start)
        clipped_end = min(end, clip_end)
        if clipped_start >= clipped_end:
            return {key: 0.0 for key in PERIOD_HOURS}
        uniform_clipped = weighted_hours(clipped_start, clipped_end, uniform_profile)
        return {key: kwh * uniform_clipped[key] / uniform_denominator for key in PERIOD_HOURS}
    clipped_start = max(start, clip_start)
    clipped_end = min(end, clip_end)
    if clipped_start >= clipped_end:
        return {key: 0.0 for key in PERIOD_HOURS}
    clipped_weights = weighted_hours(clipped_start, clipped_end, settings)
    return {key: kwh * clipped_weights[key] / denominator for key in PERIOD_HOURS}


def analyze(readings, window_start: datetime, window_end: datetime, settings: dict[str, str]) -> dict:
    totals = {key: 0.0 for key in PERIOD_HOURS}
    for row in readings:
        allocation = allocate_energy(
            datetime.fromisoformat(row["start_at"]),
            datetime.fromisoformat(row["end_at"]),
            row["kwh"],
            settings,
            window_start,
            window_end,
        )
        for key, value in allocation.items():
            totals[key] += value
    total = sum(totals.values())
    days = max((window_end - window_start).total_seconds() / 86400, 1)
    tariff = float(settings["tarifa"])
    return {
        "periods": {
            key: {
                "kwh": value,
                "cost": value * tariff,
                "weekly_kwh": value / days * 7,
                "weekly_cost": value / days * 7 * tariff,
                "monthly_kwh": value / days * 30,
                "monthly_cost": value / days * 30 * tariff,
            }
            for key, value in totals.items()
        },
        "total_kwh": total,
        "total_cost": total * tariff,
        "daily_kwh": total / days,
        "daily_cost": total / days * tariff,
        "weekly_kwh": total / days * 7,
        "weekly_cost": total / days * 7 * tariff,
        "monthly_kwh": total / days * 30,
        "monthly_cost": total / days * 30 * tariff,
    }


if __name__ == "__main__":
    create_app().run(debug=True)
