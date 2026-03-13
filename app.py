"""
Islamic Companion App — Flask Backend
Proxies AlAdhan API for prayer times, Hijri dates, and Ramadan timetables.
Optional Google Gemini integration for AI-verified Hijri dates.

Usage:
    pip install -r requirements.txt
    python app.py
"""
import os
import json
from datetime import datetime, date

import requests
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
CORS(app)

from routes.hijri import hijri_bp
app.register_blueprint(hijri_bp)

ALADHAN_BASE = "https://api.aladhan.com/v1"

# Handle Multiple API Keys
GEMINI_API_KEYS_ENV = os.getenv("GEMINI_API_KEYS", "")
if GEMINI_API_KEYS_ENV:
    GEMINI_API_KEYS = [k.strip() for k in GEMINI_API_KEYS_ENV.split(",") if k.strip()]
else:
    single_key = os.getenv("GEMINI_API_KEY", "")
    GEMINI_API_KEYS = [single_key] if single_key and single_key != "your_key_here" else []

CURRENT_GEMINI_KEY_INDEX = 0

# Simple server-side memory cache for location-based Gemini analysis
LOCATION_ANALYSIS_CACHE = {}

# ─── Helpers ────────────────────────────────────────────

def aladhan_get(path, params=None):
    """GET from AlAdhan API with error handling."""
    url = f"{ALADHAN_BASE}{path}"
    resp = requests.get(url, params=params, timeout=15)
    resp.raise_for_status()
    return resp.json()


def _call_gemini_with_retries(prompt):
    global CURRENT_GEMINI_KEY_INDEX
    import google.generativeai as genai
    
    attempts = 0
    max_attempts = len(GEMINI_API_KEYS)
    
    while attempts < max_attempts:
        current_key = GEMINI_API_KEYS[CURRENT_GEMINI_KEY_INDEX]
        try:
            genai.configure(api_key=current_key)
            model = genai.GenerativeModel("models/gemini-2.5-flash")
            response = model.generate_content(prompt)
            return response.text.strip()
        except Exception as e:
            error_str = str(e).lower()
            if "429" in error_str or "quota" in error_str or "exhausted" in error_str or "too many requests" in error_str:
                app.logger.warning(f"Gemini API key index {CURRENT_GEMINI_KEY_INDEX} hit quota/limit. Switching key.")
                CURRENT_GEMINI_KEY_INDEX = (CURRENT_GEMINI_KEY_INDEX + 1) % len(GEMINI_API_KEYS)
                attempts += 1
            else:
                app.logger.error(f"Gemini API non-quota error: {e}")
                return None
                
    app.logger.error("All Gemini API keys have exhausted their quota.")
    return None

def gemini_analyze_hijri(aladhan_hijri, city="Mumbai", country="India"):
    """
    Use Gemini to verify a Hijri date AND provide Islamic context in a single call.
    Returns analysis dict or None if Gemini unavailable.
    """
    global CURRENT_GEMINI_KEY_INDEX
    if not GEMINI_API_KEYS:
        return None

    today_str = date.today().strftime('%d %B %Y')
    # Determine region for moon-sighting context
    india_pak_region = country.lower() in ('india', 'pakistan', 'bangladesh', 'sri lanka')
    cache_key = f"{today_str}_{city}_{country}"
    
    if cache_key in LOCATION_ANALYSIS_CACHE:
        app.logger.info(f"Returning cached Gemini analysis for {city}, {country}")
        return LOCATION_ANALYSIS_CACHE[cache_key]

    hijri_str = f"{aladhan_hijri['day']} {aladhan_hijri['month']['en']} {aladhan_hijri['year']} AH"
    
    # Build region-specific guidance
    if india_pak_region:
        regional_guidance = f"""IMPORTANT REGIONAL CONTEXT:
The AlAdhan API uses the Saudi Umm al-Qura or similar calendar which is typically 1 day AHEAD of the
actual moon sighting in India, Pakistan, Bangladesh, and Sri Lanka. For these regions, the Hijri date
is almost always 1 day BEHIND the Saudi/AlAdhan date because local moon sighting committees (like the
Central Ruet-e-Hilal Committee or local Qazi committees) typically sight the moon 1 day after Saudi Arabia.

For {city}, {country}: You should almost certainly SUBTRACT 1 day from AlAdhan's date (i.e., adjust by -1).
Only keep the same date if you have strong evidence that local sighting matched Saudi Arabia this month."""
    else:
        regional_guidance = f"Adjust the day based on standard moon-sighting practices for {city}, {country}."
    
    prompt = f"""You are an advanced Islamic calendar and moon-sighting expert.
The AlAdhan API calculated today's baseline Hijri date as: {hijri_str}
City: {city}, {country}
Today's Gregorian date: {today_str}

{regional_guidance}

CRITICAL INSTRUCTION:
Do NOT attempt to independently calculate the current Islamic month or year. You MUST accept the Month and Year provided by AlAdhan ({aladhan_hijri['month']['en']} {aladhan_hijri['year']}) as the absolute ground truth. 
Your ONLY job regarding the date is to adjust the DAY number (e.g., {aladhan_hijri['day']}) by +1, -1, or 0 days based on known regional moon-sighting standard practices for {city}, {country}. Do NOT change the month name.

Please verify this Hijri date and provide Islamic context, including calculating accurate Namaz timings for the specified city and country.
Respond in this exact JSON format only:
{{
    "verified_hijri_date": "DD MonthName YYYY AH",
    "confidence": "high" or "medium" or "low",
    "note": "brief explanation of why the day was kept the same or adjusted based on local moon sighting",
    "regional_note": "any moon sighting info for this region",
    "islamic_significance": "significance of this date or general info",
    "upcoming_events": ["list of upcoming Islamic events within 30 days"],
    "fasting_recommended": true or false,
    "special_nights": "any special night info or empty string",
    "namaz_timings": {{
        "Fajr": "HH:MM AM/PM",
        "Sunrise": "HH:MM AM/PM",
        "Dhuhr": "HH:MM AM/PM",
        "Asr": "HH:MM AM/PM",
        "Maghrib": "HH:MM AM/PM",
        "Isha": "HH:MM AM/PM"
    }}
}}"""

    text = _call_gemini_with_retries(prompt)
    if not text:
        return None
        
    try:
        if "```json" in text:
            text = text.split("```json")[1].split("```")[0].strip()
        elif "```" in text:
            text = text.split("```")[1].split("```")[0].strip()
            
        result = json.loads(text)
        LOCATION_ANALYSIS_CACHE[cache_key] = result
        return result
    except Exception as e:
        app.logger.warning(f"Failed to parse Gemini response: {e}")
        return None


# ─── Prayer Times ───────────────────────────────────────

@app.route("/api/prayer/city")
def prayer_by_city():
    """GET /api/prayer/city?city=Mumbai&country=India&method=1&school=1"""
    city = request.args.get("city", "Mumbai")
    country = request.args.get("country", "India")
    method = request.args.get("method", "1")
    school = request.args.get("school", "1")

    today = date.today()
    try:
        data = aladhan_get("/timingsByCity", {
            "city": city,
            "country": country,
            "method": method,
            "school": school,
            "date_or_timestamp": today.strftime("%d-%m-%Y"),
        })
        timings = data["data"]["timings"]
        return jsonify({
            "data": {
                "prayer_times": {
                    "Fajr": timings.get("Fajr", ""),
                    "Sunrise": timings.get("Sunrise", ""),
                    "Dhuhr": timings.get("Dhuhr", ""),
                    "Asr": timings.get("Asr", ""),
                    "Maghrib": timings.get("Maghrib", ""),
                    "Isha": timings.get("Isha", ""),
                    "Imsak": timings.get("Imsak", ""),
                    "Midnight": timings.get("Midnight", ""),
                },
                "date": data["data"].get("date", {}),
                "meta": data["data"].get("meta", {}),
            }
        })
    except requests.RequestException as e:
        return jsonify({"error": f"AlAdhan API error: {str(e)}"}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/prayer/coords")
def prayer_by_coords():
    """GET /api/prayer/coords?lat=19.076&lon=72.877&method=1&school=1"""
    lat = request.args.get("lat")
    lon = request.args.get("lon")
    method = request.args.get("method", "1")
    school = request.args.get("school", "1")

    if not lat or not lon:
        return jsonify({"error": "lat and lon are required"}), 400

    today = date.today()
    try:
        data = aladhan_get(f"/timings/{today.strftime('%d-%m-%Y')}", {
            "latitude": lat,
            "longitude": lon,
            "method": method,
            "school": school,
        })
        timings = data["data"]["timings"]
        return jsonify({
            "data": {
                "prayer_times": {
                    "Fajr": timings.get("Fajr", ""),
                    "Sunrise": timings.get("Sunrise", ""),
                    "Dhuhr": timings.get("Dhuhr", ""),
                    "Asr": timings.get("Asr", ""),
                    "Maghrib": timings.get("Maghrib", ""),
                    "Isha": timings.get("Isha", ""),
                    "Imsak": timings.get("Imsak", ""),
                    "Midnight": timings.get("Midnight", ""),
                },
                "date": data["data"].get("date", {}),
                "meta": data["data"].get("meta", {}),
            }
        })
    except requests.RequestException as e:
        return jsonify({"error": f"AlAdhan API error: {str(e)}"}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── Hijri Dates ────────────────────────────────────────

@app.route("/api/hijri/today")
def hijri_today():
    """GET /api/hijri/today?city=Mumbai&country=India&adjustment=-1"""
    city = request.args.get("city", "Mumbai")
    country = request.args.get("country", "India")
    # Accept client-side hijri adjustment (default -1 for India/Pak, 0 otherwise)
    is_subcontinent = country.lower() in ("india", "pakistan", "bangladesh", "sri lanka")
    default_adj = "-1" if is_subcontinent else "0"
    adjustment = int(request.args.get("adjustment", default_adj))

    today = date.today()
    try:
        # Get base Hijri date from AlAdhan
        data = aladhan_get("/timingsByCity", {
            "city": city,
            "country": country,
            "method": "1",
            "date_or_timestamp": today.strftime("%d-%m-%Y"),
        })
        hijri = data["data"]["date"]["hijri"]
        
        # Apply day adjustment for regions where AlAdhan is typically off
        raw_day = int(hijri["day"])
        raw_month = int(hijri["month"]["number"])
        raw_year = int(hijri["year"])
        
        adjusted_day = raw_day + adjustment
        adjusted_month = raw_month
        adjusted_year = raw_year
        
        # Handle month boundaries (walking backward)
        if adjusted_day < 1:
            adjusted_month -= 1
            if adjusted_month < 1:
                adjusted_month = 12
                adjusted_year -= 1
            # Hijri months alternate 30/29 days (odd=30, even=29, except month 12 in leap years)
            if adjusted_month % 2 == 1:
                prev_month_days = 30
            elif adjusted_month == 12 and ((11 * adjusted_year + 14) % 30) < 11:
                prev_month_days = 30
            else:
                prev_month_days = 29
            adjusted_day = prev_month_days + adjusted_day  # adjusted_day is negative here
        
        # Handle walking forward
        current_month_days = 30 if raw_month % 2 == 1 else 29
        if adjusted_day > current_month_days:
            adjusted_day -= current_month_days
            adjusted_month += 1
            if adjusted_month > 12:
                adjusted_month = 1
                adjusted_year += 1

        aladhan_hijri = {
            "day": str(adjusted_day),
            "month": {"en": hijri["month"]["en"], "ar": hijri["month"]["ar"]},
            "year": str(adjusted_year),
        }
        
        app.logger.info(f"Hijri date for {city}: AlAdhan raw={raw_day}, adjustment={adjustment}, final={adjusted_day} {hijri['month']['en']} {adjusted_year}")

        # Gemini single request analysis
        gemini_analysis = gemini_analyze_hijri(aladhan_hijri, city, country)
        
        # Split the single response back into the two expected structures for the frontend
        verified_data = None
        context_data = None
        
        if gemini_analysis:
            verified_data = {
                "verified_hijri_date": gemini_analysis.get("verified_hijri_date"),
                "confidence": gemini_analysis.get("confidence"),
                "note": gemini_analysis.get("note"),
                "regional_note": gemini_analysis.get("regional_note"),
            }
            context_data = {
                "islamic_significance": gemini_analysis.get("islamic_significance"),
                "upcoming_events": gemini_analysis.get("upcoming_events", []),
                "fasting_recommended": gemini_analysis.get("fasting_recommended", False),
                "special_nights": gemini_analysis.get("special_nights"),
                "namaz_timings": gemini_analysis.get("namaz_timings")
            }

        result = {
            "data": {
                "hijri_date": {
                    "aladhan": aladhan_hijri,
                    "gemini_verified": {
                        "gemini_analysis": verified_data
                    } if verified_data else None,
                },
                "islamic_context": {
                    "data": context_data
                } if context_data else None,
            }
        }
        return jsonify(result)
    except requests.RequestException as e:
        return jsonify({"error": f"AlAdhan API error: {str(e)}"}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/hijri/to-hijri")
def gregorian_to_hijri():
    """GET /api/hijri/to-hijri?date=06-03-2026&city=Mumbai&country=India&enhance=true"""
    date_str = request.args.get("date")  # DD-MM-YYYY
    city = request.args.get("city", "Mumbai")
    country = request.args.get("country", "India")
    enhance = request.args.get("enhance", "true").lower() == "true"

    if not date_str:
        return jsonify({"error": "date parameter required (DD-MM-YYYY)"}), 400

    try:
        data = aladhan_get(f"/gToH/{date_str}")
        hijri = data["data"]["hijri"]
        aladhan_hijri = {
            "day": hijri["day"],
            "month": {"en": hijri["month"]["en"], "ar": hijri["month"]["ar"]},
            "year": hijri["year"],
        }

        # Gemini single request analysis
        gemini_analysis = None
        if enhance:
            analysis = gemini_analyze_hijri(aladhan_hijri, city, country)
            if analysis:
                gemini_analysis = {
                    "verified_hijri_date": analysis.get("verified_hijri_date"),
                    "confidence": analysis.get("confidence"),
                    "note": analysis.get("note"),
                    "regional_note": analysis.get("regional_note"),
                }

        return jsonify({
            "data": {
                "hijri_date": {
                    "aladhan": aladhan_hijri,
                    "gemini_verified": {
                        "gemini_analysis": gemini_analysis
                    } if gemini_analysis else None,
                }
            }
        })
    except requests.RequestException as e:
        return jsonify({"error": f"AlAdhan API error: {str(e)}"}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/hijri/to-gregorian")
def hijri_to_gregorian():
    """GET /api/hijri/to-gregorian?date=10-09-1447"""
    date_str = request.args.get("date")  # DD-MM-YYYY (Hijri)

    if not date_str:
        return jsonify({"error": "date parameter required (DD-MM-YYYY Hijri)"}), 400

    try:
        data = aladhan_get(f"/hToG/{date_str}")
        greg = data["data"]["gregorian"]
        return jsonify({
            "data": {
                "gregorian": {
                    "date": greg.get("date", ""),
                    "day": greg.get("day", ""),
                    "month": {
                        "en": greg["month"]["en"],
                        "number": greg["month"]["number"],
                    },
                    "year": greg.get("year", ""),
                    "weekday": {"en": greg["weekday"]["en"]},
                }
            }
        })
    except requests.RequestException as e:
        return jsonify({"error": f"AlAdhan API error: {str(e)}"}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── Ramadan ────────────────────────────────────────────

@app.route("/api/ramadan/timetable")
def ramadan_timetable():
    """GET /api/ramadan/timetable?city=Mumbai&country=India&year=1447"""
    city = request.args.get("city", "Mumbai")
    country = request.args.get("country", "India")
    hijri_year = request.args.get("year", "1447")

    try:
        # Ramadan is month 9 in Hijri calendar
        data = aladhan_get("/hijriCalendarByCity", {
            "city": city,
            "country": country,
            "month": "9",
            "year": hijri_year,
            "method": "1",
            "school": "1",
        })

        days = data.get("data", [])
        timetable = []

        for day in days:
            timings = day.get("timings", {})
            hijri = day.get("date", {}).get("hijri", {})
            greg = day.get("date", {}).get("gregorian", {})

            # Clean time strings (remove timezone parens)
            def clean(t):
                return t.split(" (")[0] if " (" in t else t

            timetable.append({
                "gregorian": greg.get("date", ""),
                "hijri": f"{hijri.get('day', '')} {hijri.get('month', {}).get('en', 'Ramadan')} {hijri.get('year', '')}",
                "sehri_ends": clean(timings.get("Imsak", "")),
                "fajr": clean(timings.get("Fajr", "")),
                "iftar": clean(timings.get("Maghrib", "")),
                "isha": clean(timings.get("Isha", "")),
            })

        return jsonify({
            "data": {
                "total_days": len(timetable),
                "timetable": timetable,
            }
        })
    except requests.RequestException as e:
        return jsonify({"error": f"AlAdhan API error: {str(e)}"}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/ramadan/today-fast")
def today_fast():
    """GET /api/ramadan/today-fast?city=Mumbai&country=India"""
    city = request.args.get("city", "Mumbai")
    country = request.args.get("country", "India")

    today = date.today()
    try:
        # Get today's date info including Hijri
        data = aladhan_get("/timingsByCity", {
            "city": city,
            "country": country,
            "method": "1",
            "school": "1",
            "date_or_timestamp": today.strftime("%d-%m-%Y"),
        })

        hijri = data["data"]["date"]["hijri"]
        hijri_month = int(hijri["month"]["number"])
        timings = data["data"]["timings"]

        def clean(t):
            return t.split(" (")[0] if " (" in t else t

        is_ramadan = hijri_month == 9

        result = {
            "data": {
                "is_ramadan": is_ramadan,
                "fasting_today": is_ramadan,
                "sehri_end": clean(timings.get("Imsak", "")),
                "iftar_time": clean(timings.get("Maghrib", "")),
            }
        }

        if not is_ramadan:
            # Calculate approximate days until next Ramadan
            # Hijri months: if current month < 9, days = (9 - month) * 29.5
            # If current month >= 9, days = (12 - month + 9) * 29.5
            current_day = int(hijri["day"])
            if hijri_month < 9:
                months_remaining = 9 - hijri_month
                days_in_current_month = 30 - current_day
                approx_days = days_in_current_month + int((months_remaining - 1) * 29.5)
            else:
                months_remaining = 12 - hijri_month + 9
                days_in_current_month = 30 - current_day
                approx_days = days_in_current_month + int((months_remaining - 1) * 29.5)

            result["data"]["next_ramadan_in_days"] = max(approx_days, 1)
            result["data"]["message"] = f"Ramadan is approximately {max(approx_days, 1)} days away. May Allah bless your patience."

        return jsonify(result)
    except requests.RequestException as e:
        return jsonify({"error": f"AlAdhan API error: {str(e)}"}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── Sehri & Iftar (Any Month) ──────────────────────────

@app.route("/api/sehri-iftar/monthly")
def sehri_iftar_monthly():
    """GET /api/sehri-iftar/monthly?city=Mumbai&country=India&month=3&year=2026
    Returns Sehri (Imsak) and Iftar (Maghrib) for every day of a Gregorian month."""
    city = request.args.get("city", "Mumbai")
    country = request.args.get("country", "India")
    month = request.args.get("month", str(date.today().month))
    year = request.args.get("year", str(date.today().year))
    method = request.args.get("method", "1")
    school = request.args.get("school", "1")

    try:
        data = aladhan_get("/calendarByCity", {
            "city": city,
            "country": country,
            "month": month,
            "year": year,
            "method": method,
            "school": school,
        })

        days = data.get("data", [])
        timetable = []

        for day in days:
            timings = day.get("timings", {})
            hijri = day.get("date", {}).get("hijri", {})
            greg = day.get("date", {}).get("gregorian", {})

            def clean(t):
                return t.split(" (")[0] if " (" in t else t

            timetable.append({
                "gregorian": greg.get("date", ""),
                "weekday": greg.get("weekday", {}).get("en", ""),
                "hijri": f"{hijri.get('day', '')} {hijri.get('month', {}).get('en', '')} {hijri.get('year', '')}",
                "hijri_month": int(hijri.get("month", {}).get("number", 0)),
                "sehri_ends": clean(timings.get("Imsak", "")),
                "fajr": clean(timings.get("Fajr", "")),
                "iftar": clean(timings.get("Maghrib", "")),
                "isha": clean(timings.get("Isha", "")),
            })

        return jsonify({
            "data": {
                "city": city,
                "month": int(month),
                "year": int(year),
                "total_days": len(timetable),
                "timetable": timetable,
            }
        })
    except requests.RequestException as e:
        return jsonify({"error": f"AlAdhan API error: {str(e)}"}), 502
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─── Health ─────────────────────────────────────────────

@app.route("/")
def health():
    return jsonify({
        "status": "running",
        "name": "Islamic Companion API",
        "version": "1.1.0",
        "endpoints": [
            "/api/prayer/city",
            "/api/prayer/coords",
            "/api/hijri/today",
            "/api/hijri/to-hijri",
            "/api/hijri/to-gregorian",
            "/api/ramadan/timetable",
            "/api/ramadan/today-fast",
            "/api/sehri-iftar/monthly",
            "/ping",
        ],
        "gemini_enabled": len(GEMINI_API_KEYS) > 0,
    })


@app.route("/settings")
def settings_page():
    return render_template("settings.html")


@app.route("/web")
def index_page():
    return render_template("index.html")


@app.route("/ping")
def ping():
    """Simple ping endpoint for cron jobs (e.g., cron-job.org) to keep the server awake."""
    return jsonify({"status": "alive", "timestamp": str(datetime.now())}), 200


if __name__ == "__main__":
    port = 5000
    print("🕌 Islamic Companion API starting...")
    print(f"   Gemini AI: {'✅ Enabled (' + str(len(GEMINI_API_KEYS)) + ' keys)' if GEMINI_API_KEYS else '❌ Disabled (set GEMINI_API_KEYS in .env)'}")
    print(f"   Server: http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=True)
