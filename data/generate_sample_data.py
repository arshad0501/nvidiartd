"""
Generates a realistic synthetic dataset of vehicle owner reviews for DriveSense AI.
Run once to create data/reviews_raw.csv
"""
import csv
import random
import argparse
from pathlib import Path

random.seed(42)

VEHICLES = [
    "Sedan LX 2024", "Sedan LX 2025", "SUV Trailmaster 2024", "SUV Trailmaster 2025",
    "EV Volt-X 2024", "EV Volt-X 2025", "Pickup RangeRunner 2024", "Compact Hatch Nova 2023",
    "Compact Hatch Nova 2024", "Crossover Aria 2024"
]

THEMES = {
    "battery": {
        "keywords": ["battery", "charge", "charging", "range", "drained", "voltage"],
        "positive": [
            "The battery holds charge really well even in winter, very impressed with the range.",
            "Charging at home overnight is seamless and the range estimate has been accurate.",
        ],
        "negative": [
            "The battery drains overnight even when the car is off, lost 15% charge parked in the garage.",
            "Charging speed at fast chargers is way below what was advertised, takes almost twice as long.",
            "Range dropped noticeably after just 8 months, now getting 40 miles less than when new.",
            "Had to jump start the 12V battery three times in two months, dealership says it's normal.",
            "The battery management system throws a voltage warning randomly on cold mornings.",
        ],
    },
    "brakes": {
        "keywords": ["brake", "brakes", "braking", "pedal", "squeak", "grind"],
        "positive": [
            "Braking feels confident and responsive, especially in emergency stops.",
        ],
        "negative": [
            "Brakes started squeaking loudly after only 5000 miles, mechanic says pads are already worn.",
            "There's a grinding noise when braking at low speed, took it in twice and it's still there.",
            "The brake pedal feels spongy and needs to be pressed almost to the floor to stop smoothly.",
            "Regenerative braking is jerky and inconsistent, makes city driving uncomfortable.",
            "Rear brakes wore out unevenly within the first year, dealer replaced under warranty but concerning.",
        ],
    },
    "infotainment": {
        "keywords": ["screen", "infotainment", "bluetooth", "software", "touchscreen", "app", "carplay"],
        "positive": [
            "The touchscreen is fast and CarPlay connects instantly every time.",
            "Software updates have actually improved the infotainment system over time.",
        ],
        "negative": [
            "Infotainment screen freezes at least once a week and requires a full restart.",
            "Bluetooth constantly disconnects mid-call, very frustrating on long drives.",
            "CarPlay randomly stops working after a software update and support has no fix.",
            "The touchscreen has noticeable lag when switching between navigation and music apps.",
            "Voice assistant misunderstands basic commands most of the time, hardly usable.",
        ],
    },
    "transmission": {
        "keywords": ["transmission", "shifting", "gear", "jerk", "clutch"],
        "positive": [
            "Gear shifts are smooth and barely noticeable, very refined transmission.",
        ],
        "negative": [
            "Transmission hesitates and jerks when shifting from first to second gear.",
            "Noticed a delay in acceleration response, like the transmission doesn't know which gear to pick.",
            "Rough shifting at low speeds, especially noticeable in stop-and-go traffic.",
            "Transmission made a clunking sound and the dealership couldn't replicate the issue.",
        ],
    },
    "interior_quality": {
        "keywords": ["interior", "seat", "trim", "rattle", "material", "dashboard"],
        "positive": [
            "Interior materials feel premium and have held up well after a year of daily use.",
            "Seats are extremely comfortable even on long road trips.",
        ],
        "negative": [
            "Dashboard trim started rattling within the first month, very annoying on rough roads.",
            "Seat stitching came apart after only a few months of normal use.",
            "Cheap plastic on the door panels scratches very easily.",
            "There's a persistent rattle from the rear door that the dealer couldn't diagnose.",
        ],
    },
    "service_experience": {
        "keywords": ["dealer", "service", "appointment", "wait", "staff", "warranty"],
        "positive": [
            "Service center was quick and the staff kept me updated throughout the repair.",
            "Dealer honored the warranty claim without any hassle, great experience overall.",
        ],
        "negative": [
            "Had to wait three weeks just to get a service appointment for a recurring issue.",
            "Service staff were dismissive about my concerns and didn't document the complaint properly.",
            "Same issue was 'fixed' twice and came back both times within days.",
            "Warranty claim was denied without a clear explanation, very poor communication.",
        ],
    },
    "hvac": {
        "keywords": ["air conditioning", "ac", "heater", "climate", "vents"],
        "positive": [
            "Climate control cools the cabin down fast even on hot days.",
        ],
        "negative": [
            "Air conditioning stopped blowing cold air after six months, still under investigation.",
            "Heater takes forever to warm up the cabin during winter mornings.",
            "Climate control settings reset randomly and the cabin gets uncomfortably warm.",
        ],
    },
}

POS_LEAD = ["Overall,", "So far,", "Honestly,", "I have to say,", ""]
NEG_LEAD = ["Unfortunately,", "To be honest,", "I'm disappointed that", "Frustratingly,", ""]


def make_review(theme_key, sentiment):
    theme = THEMES[theme_key]
    text = random.choice(theme["positive" if sentiment == "positive" else "negative"])
    lead = random.choice(POS_LEAD if sentiment == "positive" else NEG_LEAD)
    if lead:
        text = f"{lead} {text[0].lower()}{text[1:]}"
    return text


def main(output=None, seed=42):
    random.seed(seed)
    rows = []
    review_id = 1
    for _ in range(600):
        theme_key = random.choice(list(THEMES.keys()))
        # skew negative since this is a complaint-analysis use case, but keep realistic mix
        sentiment = random.choices(["negative", "positive"], weights=[0.68, 0.32])[0]
        text = make_review(theme_key, sentiment)
        vehicle = random.choice(VEHICLES)
        rating = (
            random.choice([1, 1, 2, 2, 3]) if sentiment == "negative" else random.choice([4, 4, 5, 5, 5])
        )
        rows.append({
            "review_id": review_id,
            "vehicle": vehicle,
            "review_text": text,
            "rating": rating,
        })
        review_id += 1

    # Inject a few duplicates and messy rows to make cleaning meaningful
    rows.append(dict(rows[3]))
    rows.append({"review_id": review_id, "vehicle": " ", "review_text": "  ", "rating": 3})
    review_id += 1
    rows.append({"review_id": review_id, "vehicle": "Sedan LX 2024", "review_text": None, "rating": 2})

    destination = Path(output) if output else Path(__file__).resolve().parent / "reviews_raw.csv"
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["review_id", "vehicle", "review_text", "rating"])
        writer.writeheader()
        for r in rows:
            writer.writerow(r)

    print(f"Generated {len(rows)} synthetic rows -> {destination}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate synthetic demonstration reviews, not real customer data.")
    parser.add_argument("--output", help="Destination CSV; defaults to data/reviews_raw.csv")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    main(args.output, args.seed)
