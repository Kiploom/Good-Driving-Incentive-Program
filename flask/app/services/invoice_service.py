import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from sqlalchemy import func
from sqlalchemy.orm import aliased

from app.models import (
    db,
    Sponsor,
    SponsorCompany,
    SponsorInvoice,
    Orders,
    OrderLineItem,
    Driver,
    Account,
)


class InvoiceService:
    """Business logic for generating and retrieving sponsor invoices."""

    EXCLUDED_STATUSES = {"CANCELLED", "VOIDED"}

    @staticmethod
    def _now():
        return datetime.utcnow()

    @classmethod
    def _month_bounds(cls, invoice_month: str | None):
        now = cls._now()
        if invoice_month:
            try:
                year_str, month_str = invoice_month.split("-", 1)
                year = int(year_str)
                month = int(month_str)
                period_start = datetime(year, month, 1, 0, 0, 0)
            except ValueError:
                raise ValueError("Invalid invoice month. Use YYYY-MM format.")
        else:
            period_start = datetime(now.year, now.month, 1, 0, 0, 0)
            year = period_start.year
            month = period_start.month

        is_current = (year == now.year) and (month == now.month)

        if is_current:
            period_end = now
        else:
            if month == 12:
                next_month_start = datetime(year + 1, 1, 1, 0, 0, 0)
            else:
                next_month_start = datetime(year, month + 1, 1, 0, 0, 0)
            period_end = next_month_start - timedelta(microseconds=1)

        return period_start, period_end, is_current

    @classmethod
    def generate_invoice_for_month(
        cls,
        sponsor_id: str,
        invoice_month: str | None,
        generated_by_account_id: str,
        notes: str | None = None,
    ):
        """Generate (and persist) a sponsor invoice for the requested month."""
        sponsor = Sponsor.query.filter_by(SponsorID=sponsor_id).first()
        if not sponsor:
            raise ValueError("Sponsor not found.")

        period_start, period_end, _ = cls._month_bounds(invoice_month)
        orders_data, totals = cls._collect_orders_data(sponsor, period_start, period_end)

        invoice_date = period_start.date()

        invoice = (
            SponsorInvoice.query.filter_by(SponsorID=sponsor.SponsorID, InvoiceMonth=invoice_date)
            .order_by(SponsorInvoice.GeneratedAt.desc())
            .first()
        )

        if invoice:
            invoice.PeriodStart = period_start
            invoice.PeriodEnd = period_end
            invoice.TotalOrders = totals["total_orders"]
            invoice.TotalPoints = totals["total_points"]
            invoice.TotalAmount = totals["total_amount"]
            invoice.GeneratedAt = cls._now()
            invoice.GeneratedBy = generated_by_account_id
            invoice.Notes = notes
        else:
            invoice = SponsorInvoice(
                SponsorInvoiceID=str(uuid.uuid4()),
                SponsorCompanyID=sponsor.SponsorCompanyID,
                SponsorID=sponsor.SponsorID,
                InvoiceMonth=invoice_date,
                PeriodStart=period_start,
                PeriodEnd=period_end,
                TotalOrders=totals["total_orders"],
                TotalPoints=totals["total_points"],
                TotalAmount=totals["total_amount"],
                GeneratedAt=cls._now(),
                GeneratedBy=generated_by_account_id,
                Notes=notes,
                Status="PENDING",
            )
            db.session.add(invoice)

        db.session.commit()

        return cls.serialize_invoice(invoice, orders_data, sponsor)

    @classmethod
    def get_invoice_for_month(cls, sponsor_id: str, invoice_month: str | None):
        sponsor = Sponsor.query.filter_by(SponsorID=sponsor_id).first()
        if not sponsor:
            raise ValueError("Sponsor not found.")

        period_start, period_end, _ = cls._month_bounds(invoice_month)
        invoice_date = period_start.date()

        invoice = (
            SponsorInvoice.query.filter_by(SponsorID=sponsor.SponsorID, InvoiceMonth=invoice_date)
            .order_by(SponsorInvoice.GeneratedAt.desc())
            .first()
        )

        if invoice:
            orders_data, _ = cls._collect_orders_data(sponsor, invoice.PeriodStart, invoice.PeriodEnd)
            return cls.serialize_invoice(invoice, orders_data, sponsor)

        orders_data, totals = cls._collect_orders_data(sponsor, period_start, period_end)

        draft_invoice = SimpleNamespace(
            SponsorInvoiceID=None,
            InvoiceMonth=invoice_date,
            PeriodStart=period_start,
            PeriodEnd=period_end,
            TotalOrders=totals["total_orders"],
            TotalPoints=totals["total_points"],
            TotalAmount=totals["total_amount"],
            GeneratedAt=None,
            GeneratedBy=None,
            Notes=None,
        )

        return cls.serialize_invoice(draft_invoice, orders_data, sponsor)

    @staticmethod
    def _format_invoice_month(invoice_month_value):
        if invoice_month_value is None:
            return None
        if hasattr(invoice_month_value, "strftime"):
            return invoice_month_value.strftime("%Y-%m")
        return str(invoice_month_value)

    @staticmethod
    def _as_decimal(value):
        if value is None:
            return Decimal("0")
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))

    @classmethod
    def _decimal_to_float(cls, value):
        decimal_value = cls._as_decimal(value)
        return float(decimal_value)

    @classmethod
    def _collect_orders_data(cls, sponsor: Sponsor, period_start, period_end):
        DriverAccount = aliased(Account)
        orders_query = (
            db.session.query(Orders, Driver, DriverAccount)
            .join(Driver, Driver.DriverID == Orders.DriverID)
            .join(DriverAccount, DriverAccount.AccountID == Driver.AccountID)
            .filter(
                Orders.SponsorID == sponsor.SponsorID,
                Orders.CreatedAt >= period_start,
                Orders.CreatedAt <= period_end,
            )
        )

        sponsor_rate = (
            Decimal(str(sponsor.PointToDollarRate))
            if sponsor.PointToDollarRate is not None
            else Decimal("0.00")
        )

        order_ids = []
        orders_data = []
        total_points = 0
        total_amount = Decimal("0.00")

        for order, driver, driver_account in orders_query:
            if order.Status and str(order.Status).upper() in cls.EXCLUDED_STATUSES:
                continue

            order_total_points = order.TotalPoints or 0
            if order.TotalAmount is not None:
                order_amount_decimal = Decimal(str(order.TotalAmount))
            else:
                order_amount_decimal = sponsor_rate * Decimal(order_total_points)

            orders_data.append(
                {
                    "order": order,
                    "driver": driver,
                    "driver_account": driver_account,
                    "points": order_total_points,
                    "amount": order_amount_decimal,
                }
            )
            order_ids.append(order.OrderID)
            total_points += order_total_points
            total_amount += order_amount_decimal

        line_item_counts = {}
        line_item_details = {}
        if order_ids:
            counts = (
                db.session.query(OrderLineItem.OrderID, func.count(OrderLineItem.OrderLineItemID))
                .filter(OrderLineItem.OrderID.in_(order_ids))
                .group_by(OrderLineItem.OrderID)
                .all()
            )
            line_item_counts = {order_id: count for order_id, count in counts}

            items = (
                db.session.query(OrderLineItem)
                .filter(OrderLineItem.OrderID.in_(order_ids))
                .order_by(OrderLineItem.OrderID.asc(), OrderLineItem.CreatedAt.asc())
                .all()
            )
            for item in items:
                line_item_details.setdefault(item.OrderID, []).append(item)

        enriched_orders = []
        for record in orders_data:
            order = record["order"]
            driver = record["driver"]
            driver_account = record["driver_account"]

            driver_name = None
            if driver_account:
                driver_name = f"{(driver_account.FirstName or '').strip()} {(driver_account.LastName or '').strip()}".strip()

            item_entries = []
            for item in line_item_details.get(order.OrderID, []):
                line_total_points = item.LineTotalPoints
                if line_total_points is None:
                    qty = item.Quantity or 0
                    unit = item.UnitPoints or 0
                    line_total_points = qty * unit
                line_total_points = int(line_total_points or 0)
                line_total_amount = sponsor_rate * Decimal(line_total_points)
                item_entries.append(
                    {
                        "title": item.Title,
                        "product_id": item.ProductID,
                        "quantity": item.Quantity or 0,
                        "unit_points": item.UnitPoints or 0,
                        "line_total_points": line_total_points,
                        "line_total_amount": line_total_amount,
                    }
                )

            enriched_orders.append(
                {
                    "order_id": order.OrderID,
                    "order_number": order.OrderNumber,
                    "order_created_at": order.CreatedAt.isoformat() if order.CreatedAt else None,
                    "driver_id": driver.DriverID if driver else None,
                    "driver_name": driver_name or None,
                    "driver_email": driver_account.Email if driver_account else None,
                    "total_points": record["points"],
                    "total_amount": record["amount"],
                    "line_item_count": line_item_counts.get(order.OrderID, 0),
                    "line_items": item_entries,
                }
            )

        totals = {
            "total_orders": len(enriched_orders),
            "total_points": total_points,
            "total_amount": total_amount,
        }
        return enriched_orders, totals

    @classmethod
    def serialize_invoice(cls, invoice: SponsorInvoice, orders: list[dict], sponsor: Sponsor):
        if not invoice:
            return None

        invoice_month_str = cls._format_invoice_month(invoice.InvoiceMonth)
        is_finalized = bool(getattr(invoice, "SponsorInvoiceID", None))
        status_value = getattr(invoice, "Status", "PENDING") or "PENDING"
        status_value = str(status_value).upper()

        return {
            "invoice": {
                "id": getattr(invoice, "SponsorInvoiceID", None),
                "invoice_month": invoice_month_str,
                "period_start": invoice.PeriodStart.isoformat() if invoice.PeriodStart else None,
                "period_end": invoice.PeriodEnd.isoformat() if invoice.PeriodEnd else None,
                "total_orders": invoice.TotalOrders or 0,
                "total_points": invoice.TotalPoints or 0,
                "total_amount": cls._decimal_to_float(invoice.TotalAmount),
                "generated_at": invoice.GeneratedAt.isoformat() if invoice.GeneratedAt else None,
                "generated_by": invoice.GeneratedBy,
                "notes": invoice.Notes,
                "finalized": is_finalized,
                "status": status_value,
            },
            "sponsor": {
                "id": sponsor.SponsorID,
                "company": sponsor.Company,
                "point_to_dollar_rate": cls._decimal_to_float(sponsor.PointToDollarRate),
            },
            "orders": [
                {
                    "order_id": order["order_id"],
                    "order_number": order["order_number"],
                    "order_created_at": order["order_created_at"],
                    "driver_id": order["driver_id"],
                    "driver_name": order["driver_name"],
                    "driver_email": order["driver_email"],
                    "total_points": order["total_points"] or 0,
                    "total_amount": cls._decimal_to_float(order["total_amount"]),
                    "line_item_count": order["line_item_count"] or 0,
                    "line_items": [
                        {
                            "title": item["title"],
                            "product_id": item["product_id"],
                            "quantity": item["quantity"],
                            "unit_points": item["unit_points"],
                            "line_total_points": item["line_total_points"],
                            "line_total_amount": cls._decimal_to_float(item["line_total_amount"]),
                        }
                        for item in order.get("line_items", [])
                    ],
                }
                for order in orders
            ],
        }

    @classmethod
    def update_invoice_status(cls, invoice_id: str, status: str, updated_by: str):
        allowed = {"PAID", "PENDING"}
        status_upper = status.upper()
        if status_upper not in allowed:
            raise ValueError("Invalid status. Must be PAID or PENDING.")

        invoice = SponsorInvoice.query.filter_by(SponsorInvoiceID=invoice_id).first()
        if not invoice:
            raise ValueError("Invoice not found.")

        invoice.Status = status_upper
        invoice.GeneratedBy = updated_by or invoice.GeneratedBy
        invoice.GeneratedAt = cls._now()

        db.session.commit()

        sponsor = Sponsor.query.filter_by(SponsorID=invoice.SponsorID).first()
        generated_by_account = None
        if invoice.GeneratedBy:
            generated_by_account = Account.query.filter_by(AccountID=invoice.GeneratedBy).first()
        orders_data, _ = cls._collect_orders_data(sponsor, invoice.PeriodStart, invoice.PeriodEnd)
        payload = cls.serialize_invoice(invoice, orders_data, sponsor)
        if generated_by_account:
            full_name = " ".join(
                filter(
                    None,
                    [
                        (generated_by_account.FirstName or "").strip(),
                        (generated_by_account.LastName or "").strip(),
                    ],
                )
            ).strip()
            if full_name:
                payload["invoice"]["generated_by_name"] = full_name
        return payload

    @classmethod
    def get_invoice_by_id(cls, sponsor_invoice_id: str):
        invoice = (
            SponsorInvoice.query.filter_by(SponsorInvoiceID=sponsor_invoice_id)
            .first()
        )
        if not invoice:
            raise ValueError("Invoice not found.")

        sponsor = Sponsor.query.filter_by(SponsorID=invoice.SponsorID).first()
        generated_by_account = None
        if invoice.GeneratedBy:
            generated_by_account = Account.query.filter_by(AccountID=invoice.GeneratedBy).first()

        if not sponsor:
            raise ValueError("Sponsor not found for invoice.")

        orders_data, _ = cls._collect_orders_data(sponsor, invoice.PeriodStart, invoice.PeriodEnd)
        payload = cls.serialize_invoice(invoice, orders_data, sponsor)
        if generated_by_account:
            full_name = " ".join(
                filter(
                    None,
                    [
                        (generated_by_account.FirstName or "").strip(),
                        (generated_by_account.LastName or "").strip(),
                    ],
                )
            ).strip()
            if full_name:
                payload["invoice"]["generated_by_name"] = full_name
        return payload

    @classmethod
    def _parse_month_to_date(cls, month_str: str | None):
        if not month_str:
            return None
        try:
            year_str, month_str = month_str.split("-", 1)
            year = int(year_str)
            month = int(month_str)
            return datetime(year, month, 1).date()
        except ValueError as exc:
            raise ValueError("Invalid month format. Use YYYY-MM.") from exc

    @classmethod
    def get_invoice_log(
        cls,
        company_filter: str | None = None,
        start_month: str | None = None,
        end_month: str | None = None,
    ):
        subquery = (
            db.session.query(
                SponsorInvoice.SponsorCompanyID.label("company_id"),
                SponsorInvoice.InvoiceMonth.label("invoice_month"),
                func.max(SponsorInvoice.GeneratedAt).label("max_generated_at"),
            )
            .group_by(SponsorInvoice.SponsorCompanyID, SponsorInvoice.InvoiceMonth)
            .subquery()
        )

        query = (
            db.session.query(SponsorInvoice, Sponsor, SponsorCompany)
            .join(
                subquery,
                (SponsorInvoice.SponsorCompanyID == subquery.c.company_id)
                & (SponsorInvoice.InvoiceMonth == subquery.c.invoice_month)
                & (SponsorInvoice.GeneratedAt == subquery.c.max_generated_at),
            )
            .outerjoin(Sponsor, Sponsor.SponsorID == SponsorInvoice.SponsorID)
            .outerjoin(SponsorCompany, SponsorCompany.SponsorCompanyID == SponsorInvoice.SponsorCompanyID)
        )

        if company_filter:
            query = query.filter(
                func.lower(
                    func.coalesce(SponsorCompany.CompanyName, Sponsor.Company)
                )
                == company_filter.lower()
            )

        start_date = cls._parse_month_to_date(start_month)
        end_date = cls._parse_month_to_date(end_month)

        if start_date and end_date and start_date > end_date:
            raise ValueError("Start month must be on or before end month.")

        if start_date:
            query = query.filter(SponsorInvoice.InvoiceMonth >= start_date)
        if end_date:
            query = query.filter(SponsorInvoice.InvoiceMonth <= end_date)

        results = query.order_by(
            SponsorInvoice.InvoiceMonth.desc(),
            SponsorCompany.CompanyName.asc(),
            SponsorInvoice.GeneratedAt.desc(),
        ).all()

        log_entries = []
        for invoice, sponsor, sponsor_company in results:
            company_name = (
                sponsor_company.CompanyName
                if sponsor_company and sponsor_company.CompanyName
                else sponsor.Company if sponsor else None
            )

            status_value = str(getattr(invoice, "Status", "PENDING") or "PENDING").upper()

            generated_name = ""
            generated_account = None
            if invoice.GeneratedBy:
                generated_account = Account.query.filter_by(AccountID=invoice.GeneratedBy).first()
            if generated_account:
                generated_name = " ".join(
                    filter(
                        None,
                        [
                            (generated_account.FirstName or "").strip(),
                            (generated_account.LastName or "").strip(),
                        ],
                    )
                ).strip()

            log_entries.append(
                {
                    "invoice_id": invoice.SponsorInvoiceID,
                    "sponsor_id": sponsor.SponsorID if sponsor else None,
                    "sponsor_company_id": invoice.SponsorCompanyID,
                    "company_name": company_name,
                    "invoice_month": cls._format_invoice_month(invoice.InvoiceMonth),
                    "total_orders": invoice.TotalOrders or 0,
                    "total_points": invoice.TotalPoints or 0,
                    "total_amount": cls._decimal_to_float(invoice.TotalAmount),
                    "generated_at": invoice.GeneratedAt.isoformat() if invoice.GeneratedAt else None,
                    "generated_by": invoice.GeneratedBy,
                    "generated_by_name": generated_name or None,
                    "status": status_value,
                }
            )

        return log_entries

