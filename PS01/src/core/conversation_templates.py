"""
Static conversation templates for fallback when Ollama is unavailable.
Used as backup NL generation when phi4-mini is slow or offline.
"""

import random
from typing import Dict, List

TEMPLATES: Dict[str, List[str]] = {
    "recall_start": [
        "Last time you mentioned {fact}.",
        "From our previous conversation, I noted {fact}.",
        "I can see from our last session that {fact}.",
        "When we spoke before, you had mentioned {fact}.",
    ],
    "continuation": [
        "Shall I continue from where we left off?",
        "Would you like to pick up where we stopped?",
        "Should we continue with your {loan_type} application?",
        "Let's continue from where we left things last time.",
    ],
    "verification_ask": [
        "To move forward, we'll need to verify your {field}.",
        "The next step is to confirm your {field} with a document.",
        "Could you arrange {field} verification for us?",
        "We'll need to verify {field} before we proceed.",
    ],
    "greeting_new": [
        "Welcome! I'm here to help with your loan application.",
        "Hello! How can I assist you with your banking needs today?",
        "Hi there! Let's get started with your application.",
    ],
    "greeting_returning": [
        "Welcome back, {name}! Good to hear from you again.",
        "Hi {name}! I remember you from our last conversation.",
        "{name}, great to connect with you again!",
    ],
    "greeting_repeat": [
        "Hi {name}! I can see we've been working on your application a few times now.",
        "Welcome back, {name}! Looking at our history, we've made good progress.",
        "{name}, thanks for staying engaged. We're nearly there with your application.",
    ],
    "income_summary": [
        "Your monthly income is ₹{amount}.",
        "I see your income is ₹{amount} per month.",
        "Based on our records, you earn ₹{amount} each month.",
    ],
    "property_summary": [
        "The property is located in {location}.",
        "You're looking at a property in {location}.",
        "The asset is in {location}.",
    ],
    "eligibility_msg": [
        "Based on your profile, your loan eligibility is approximately ₹{amount}.",
        "With your current income and existing EMI, you qualify for around ₹{amount}.",
        "Your indicative loan limit is ₹{amount}.",
    ],
}


def fill_template(template_key: str, **kwargs) -> str:
    """
    Pick random template from list and fill variables.
    
    Args:
        template_key: Key in TEMPLATES dict
        **kwargs: Variables to fill in template
    
    Returns:
        Filled template string or default if key not found
    """
    templates = TEMPLATES.get(template_key, ["How can I help?"])
    template = random.choice(templates)
    try:
        return template.format(**kwargs)
    except (KeyError, ValueError):
        # If variable not provided, return template as-is
        return template


def get_fact_summary_template(fact_type: str, fact_value: str) -> str:
    """
    Get a template sentence for a single fact.
    
    Args:
        fact_type: Type of fact (income, property_location, etc.)
        fact_value: The value of the fact
    
    Returns:
        Natural language fact summary
    """
    if fact_type == "income":
        return fill_template("income_summary", amount=fact_value)
    elif fact_type == "property_location":
        return fill_template("property_summary", location=fact_value)
    elif fact_type == "loan_eligibility":
        return fill_template("eligibility_msg", amount=fact_value)
    return f"You mentioned {fact_value}."
