"""
CBS (Core Banking System) pre-seeding module.

Fetches verified customer facts from CBS API before session starts.
All facts marked with verified=True, source="cbs_fetched".
"""

from typing import List, Dict, Any, Optional


class CBSPreseeder:
    """Fetch verified facts from CBS before agent speaks."""

    def __init__(self, cbs_api):
        """
        Initialize CBS preseeder.

        Args:
            cbs_api: CBS API client with get_customer(customer_id) method
        """
        self.cbs_api = cbs_api

    async def preseed(self, customer_id: str) -> List[Dict[str, Any]]:
        """
        Fetch CBS facts for customer and mark as verified.

        Args:
            customer_id: Customer ID to lookup in CBS

        Returns:
            List of facts with verified=True, source="cbs_fetched".
            Empty list if customer not found in CBS (new customer flow).
        """
        # Fetch customer data from CBS
        cbs_data = await self.cbs_api.get_customer(customer_id)

        # Return empty list if customer not found (new customer)
        if cbs_data is None:
            return []

        # Transform CBS data into facts
        facts = []

        # Customer name
        if "customer_name" in cbs_data:
            facts.append({
                "type": "customer_name",
                "value": cbs_data["customer_name"],
                "verified": True,
                "source": "cbs_fetched"
            })

        # Account vintage (try both field names)
        vintage = cbs_data.get("account_vintage_years") or cbs_data.get("account_vintage_months")
        if vintage:
            facts.append({
                "type": "account_vintage_years",
                "value": vintage,
                "verified": True,
                "source": "cbs_fetched"
            })

        # Average monthly credit (try both field names)
        credit = cbs_data.get("avg_monthly_credit_inr") or cbs_data.get("avg_monthly_credit")
        if credit:
            facts.append({
                "type": "avg_monthly_credit_inr",
                "value": credit,
                "verified": True,
                "source": "cbs_fetched"
            })

        # Existing EMIs (try both field names)
        emis = cbs_data.get("existing_emis_inr") or cbs_data.get("existing_emis")
        if emis is not None:
            facts.append({
                "type": "existing_emis_inr",
                "value": emis,
                "verified": True,
                "source": "cbs_fetched"
            })

        # Credit behaviour
        if "credit_behaviour" in cbs_data:
            facts.append({
                "type": "credit_behaviour",
                "value": cbs_data["credit_behaviour"],
                "verified": True,
                "source": "cbs_fetched"
            })

        # Savings balance tier
        if "savings_balance_tier" in cbs_data:
            facts.append({
                "type": "savings_balance_tier",
                "value": cbs_data["savings_balance_tier"],
                "verified": True,
                "source": "cbs_fetched"
            })

        return facts
