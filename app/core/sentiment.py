"""VADER polarity intensity. Compound is signed, not calibrated probability."""
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

_analyzer = SentimentIntensityAnalyzer()


def score_text(text):
    compound = float(_analyzer.polarity_scores(text)["compound"])
    label = "positive" if compound >= 0.05 else "negative" if compound <= -0.05 else "neutral"
    return label, compound
