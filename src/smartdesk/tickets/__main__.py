"""Ticket CLI for manual checks and demo data: `python -m smartdesk.tickets`.

    create --email E --category IT|HR --summary S --description D [--priority P]
    list   --email E
    show   KEY --email E

`create` shows the ticket and asks for confirmation before anything is sent.
It uses the same labels and idempotency as SmartDesk, so demo tickets made
here are found by status lookups.
"""

import argparse
import sys
import uuid

from pydantic import ValidationError

from smartdesk.config import get_settings
from smartdesk.tickets import JiraError, TicketDraft, build_ticket_service, derive_op_id


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m smartdesk.tickets")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create", help="create a ticket (asks for confirmation)")
    create.add_argument("--email", required=True)
    create.add_argument("--category", required=True, choices=["IT", "HR"])
    create.add_argument("--summary", required=True)
    create.add_argument("--description", required=True)
    create.add_argument("--priority", choices=["Low", "Medium", "High", "Critical"])
    create.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    listing = commands.add_parser("list", help="list an employee's tickets")
    listing.add_argument("--email", required=True)
    show = commands.add_parser("show", help="show one ticket's status and comments")
    show.add_argument("key")
    show.add_argument("--email", required=True)
    args = parser.parse_args(argv)

    settings = get_settings()
    if not settings.jira_configured:
        print("Jira is not configured; set the JIRA_* variables in .env.", file=sys.stderr)
        return 1
    service = build_ticket_service(settings)

    try:
        if args.command == "create":
            try:
                draft = TicketDraft(
                    email=args.email,
                    summary=args.summary,
                    description=args.description,
                    category=args.category,
                    priority=args.priority,
                )
            except ValidationError as exc:
                print(f"Invalid ticket: {exc}", file=sys.stderr)
                return 2
            print(
                f"Email: {draft.email}\nCategory: {draft.category}\nPriority: {draft.priority or '(Jira default)'}\n"
                f"Summary: {draft.summary}\nDescription:\n{draft.description}"
            )
            if not args.yes and input("\nCreate this ticket? [y/N] ").strip().lower() != "y":
                print("Cancelled; nothing was created.")
                return 0
            ticket = service.create_ticket(draft, derive_op_id(f"cli-{uuid.uuid4()}", draft))
            print(f"Created {ticket.key}: {ticket.url}")

        elif args.command == "list":
            tickets = service.list_tickets(args.email)
            if not tickets:
                print("No tickets found for this email.")
            for t in tickets:
                print(f"{t.key}  [{t.status}]  {t.category}  {t.summary}  (updated {t.updated[:10]})  {t.url}")

        else:
            ticket = service.get_ticket(args.email, args.key)
            if ticket is None:
                print(f"No ticket {args.key} found for this email.")
                return 1
            print(f"{ticket.key}: {ticket.summary}\nStatus: {ticket.status} ({ticket.status_category})")
            print(f"Category: {ticket.category}  Priority: {ticket.priority or '-'}  URL: {ticket.url}")
            print(f"\n{ticket.description}\n\nComments ({len(ticket.comments)}):")
            for c in ticket.comments:
                print(f"- {c.author}, {c.created[:16]}: {c.body}")
    except ValueError as exc:  # invalid email
        print(f"Invalid input: {exc}", file=sys.stderr)
        return 2
    except JiraError as exc:
        print(f"Jira error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
