"""Inspectable complaint routing independent of global review sentiment.

Rules are broad linguistic cues, not diagnoses. Matched spans are persisted so
reviewers can challenge false positives. A positive component mention alone
does not trigger routing. Rule and negative-polarity errors remain possible.
"""
import re

CUE_PATTERNS = {
    "failure": r"\b(?:fail(?:s|ed|ing|ure)?|broken|broke|malfunction(?:s|ed|ing)?|defect(?:ive|s)?|stopped working|stops working|doesn['’]t work|does not work|won['’]t (?:start|charge|stop)|would not start|could not stop)\b",
    "intermittent": r"\b(?:freez(?:e|es|ing)|froze|disconnect(?:s|ed|ing)?|reset(?:s|ting)?|restart|warning|leak(?:s|ed|ing)?|stall(?:s|ed|ing)?|overheat(?:s|ed|ing)?|smoke|fire)\b",
    "mechanical": r"\b(?:grind(?:s|ing)?|squeak(?:s|ing)?|spongy|jerk(?:s|y|ing)?|hesitat(?:e|es|ion)|clunk(?:s|ing)?|rattl(?:e|es|ing)|rough shifting|worn|wore|came apart|scratches|lag|misunderstands)\b",
    "service": r"\b(?:denied|dismissive|poor communication|recurring issue|came back|no fix|no resolution|wait(?:ed)? .*?(?:weeks|months)|unresolved|unusable|hardly usable)\b",
    "degradation": r"\b(?:drain(?:s|ed|ing)?|dropped|below .*?advertised|takes forever|uncomfortably|not .*?(?:cold|warm|respond|connect)|stopped blowing)\b",
}
COMPILED = {key: re.compile(pattern, re.I) for key, pattern in CUE_PATTERNS.items()}
NEGATED_CUE = re.compile(r"\b(?:no|without|never|not|doesn['’]t|does not)\s+(?:any\s+)?(?:signs? of\s+)?$", re.I)


def complaint_evidence(text, sentiment, mode="complaint_aware"):
    matches = []
    if mode == "complaint_aware":
        for rule, pattern in COMPILED.items():
            for match in pattern.finditer(text):
                if NEGATED_CUE.search(text[max(0, match.start()-30):match.start()]):
                    continue
                matches.append({"rule": rule, "span": match.group(), "start": match.start(), "end": match.end()})
    if sentiment == "negative":
        matches.insert(0, {"rule": "negative_sentiment", "span": "", "start": None, "end": None})
    return bool(matches), matches
