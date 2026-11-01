"""The approved KB topic plan and the deliberate gaps.

`TOPICS` lists every document the generator writes. `GAPS` lists realistic
topics that are intentionally *not* covered so escalation can be tested;
the generator drops source records about them and rejects generated text
that mentions them.
"""

import re
from dataclasses import dataclass

from smartdesk.kb.documents import Domain


@dataclass(frozen=True)
class Topic:
    doc_id: str
    title: str
    domain: Domain
    category: str
    subcategory: str
    brief: str  # what the document must cover
    source: str | None  # "it_tickets", "hr_qa", or None for purely synthetic


@dataclass(frozen=True)
class Gap:
    gap_id: str
    description: str
    forbidden: re.Pattern[str]  # must never appear in generated KB text


def _it(slug: str, title: str, sub: str, brief: str) -> Topic:
    return Topic(f"it-{slug}", title, Domain.IT, "IT Support", sub, brief, "it_tickets")


def _hr(slug: str, title: str, sub: str, brief: str) -> Topic:
    return Topic(f"hr-{slug}", title, Domain.HR, "HR Policies", sub, brief, "hr_qa")


def _onb(slug: str, title: str, sub: str, brief: str, domain: Domain = Domain.HR) -> Topic:
    return Topic(f"onb-{slug}", title, domain, "Onboarding", sub, brief, "hr_qa")


def _pay(slug: str, title: str, sub: str, brief: str) -> Topic:
    return Topic(f"pay-{slug}", title, Domain.HR, "Payroll & Compensation", sub, brief, "hr_qa")


TOPICS: tuple[Topic, ...] = (
    # --- IT Support (18) ---
    _it("password-reset", "Password Reset", "Accounts",
        "Self-service password reset via the password portal, password rules and expiry, what to do if the portal fails."),
    _it("account-lockout", "Account Lockout and Unlock", "Accounts",
        "Why accounts lock (failed attempts, stale credentials on phones), self-service unlock, when to call the Service Desk."),
    _it("mfa-setup", "Multi-Factor Authentication (MFA) Setup", "Security",
        "Enrolling Okta Verify, push vs code, new phone or lost phone, MFA reset by the Service Desk."),
    _it("vpn-setup", "VPN Setup for Remote Work", "Network",
        "Installing and connecting Cisco Secure Client on Windows, macOS and Linux, who needs VPN, connection steps."),
    _it("vpn-troubleshooting", "VPN Troubleshooting", "Network",
        "Common VPN errors (cannot connect, authentication failed, frequent drops, slow over VPN) and fixes; what to include when escalating."),
    _it("software-requests", "Software Installation and Licence Requests", "Software",
        "Installing pre-approved apps from Software Center/Self Service, requesting new software or a paid licence in ServiceHub, approval and lead times."),
    _it("corporate-wifi", "Connecting to Corporate Wi-Fi", "Network",
        "Joining NovaTech-Corp with Okta credentials on laptops and phones, certificate prompts, fixing failed connections."),
    _it("guest-wifi", "Guest Wi-Fi Access", "Network",
        "Getting a guest voucher for visitors, validity, acceptable use, guest network limits."),
    _it("mobile-email", "Email on Your Mobile Device", "Communication",
        "Setting up Outlook mobile for Microsoft 365 on iOS/Android, Intune app protection, troubleshooting sync."),
    _it("outlook-calendar", "Outlook and Calendar Issues", "Communication",
        "Common Outlook problems: not syncing, shared calendars and mailboxes, meeting invites, profile repair."),
    _it("shared-drives", "Accessing Shared Drives and SharePoint", "Software",
        "Requesting access to SharePoint sites and network shares, permission errors, owner approval, mapping drives."),
    _it("remote-desktop", "Remote Desktop Access", "Network",
        "When remote desktop is allowed, requesting access, connecting over VPN, common connection errors."),
    _it("slow-network", "Troubleshooting Slow Internet and Network", "Network",
        "Diagnosing slow connections at home and in office, speed checks, Wi-Fi vs wired, when to raise an incident."),
    _it("app-crashes", "Application Crashes and Freezes", "Software",
        "Basic troubleshooting for crashing or freezing apps: updates, restart, clearing cache, reinstall, collecting logs for IT."),
    _it("sso-cloud-access", "Single Sign-On and Cloud App Access", "Accounts",
        "Accessing cloud tools via the Okta dashboard, requesting a new app tile, 'not assigned' errors, onboarding/offboarding access."),
    _it("security-incidents", "Reporting Phishing and Security Incidents", "Security",
        "Recognising phishing, the Report Phishing button, what to do after clicking a suspicious link, reporting lost devices or security alerts."),
    _it("video-conferencing", "Microsoft Teams Meetings and Audio/Video", "Communication",
        "Joining and hosting Teams meetings, fixing microphone/camera/screen-share problems, meeting room etiquette."),
    _it("data-backup", "Data Backup and File Recovery", "Software",
        "OneDrive backup of Desktop/Documents, restoring deleted files and previous versions, retention, what is not backed up."),
    # --- HR Policies (12) ---
    _hr("leave-policy", "Leave Policy", "Leave",
        "Casual, sick, earned, maternity, paternity leave and comp-off: entitlements, eligibility, approval, carry-forward and encashment."),
    _hr("public-holidays", "Public and Floating Holidays", "Leave",
        "Fixed public holidays, floating holidays, how to choose them, working on a holiday and comp-off."),
    _hr("hybrid-work", "Hybrid and Work-from-Home Policy", "Work Arrangements",
        "Office days, anchor days, extra remote days, fully remote exceptions, home-working expectations, internet allowance."),
    _hr("expense-reimbursement", "Expense Reimbursement", "Reimbursement",
        "What is reimbursable, submission in PeopleHub with receipts, deadlines, approval flow, payment timing, rejected claims."),
    _hr("code-of-conduct", "Code of Conduct", "Conduct",
        "Professional behaviour, conflicts of interest, confidentiality, use of company assets, social media, consequences of breaches."),
    _hr("anti-harassment", "Prevention of Sexual Harassment (POSH) and Anti-Harassment", "Conduct",
        "Definition of harassment, Internal Committee, how to file a complaint, timelines, confidentiality, non-retaliation."),
    _hr("anti-bribery", "Anti-Bribery and Gifts Policy", "Conduct",
        "Prohibited payments, gifts and hospitality limits, declaring gifts, dealing with government officials, reporting concerns."),
    _hr("performance-reviews", "Performance Review Cycle", "Performance",
        "Half-yearly cycle, goal setting, self and manager reviews, ratings, calibration, increments, performance improvement plans."),
    _hr("grievance-whistleblower", "Grievance Redressal and Whistleblower Policy", "Conduct",
        "Raising workplace grievances, escalation levels, anonymous whistleblowing, protection from retaliation."),
    _hr("health-insurance", "Health Insurance and Benefits", "Benefits",
        "Group health insurance cover and dependants, term life, making a claim, cashless hospitals, adding a new dependant."),
    _hr("resignation-exit", "Resignation, Notice Period and Exit", "Separation",
        "Resigning in PeopleHub, notice periods, buyout, exit checklist, asset return, full and final settlement, relieving letter."),
    _hr("learning-budget", "Learning and Development Budget", "Learning",
        "Annual learning budget, eligible courses and certifications, approval, claiming, internal training."),
    # --- Onboarding (5) ---
    _onb("day-one", "Your First Day at NovaTech", "Day One",
         "Day-one schedule, where to go, what to bring, HR induction, first-week checklist."),
    _onb("it-equipment", "IT Equipment Allocation for New Joiners", "Equipment",
         "Laptop models by role, when you get it, accessories, first login and setup, returning equipment.", Domain.IT),
    _onb("buddy-programme", "Buddy Programme", "Integration",
         "What a buddy does, how buddies are assigned, the 90-day check-ins, being a buddy."),
    _onb("probation", "Probation Period", "Employment",
         "Length of probation, confirmation process, extension, notice period during probation, leave during probation."),
    _onb("benefits-enrolment", "Benefits Enrolment for New Joiners", "Benefits",
         "Enrolling in health insurance within 30 days, adding dependants, PF and gratuity nomination, missing the window."),
    # --- Payroll & Compensation (5) ---
    _pay("payday", "Pay-Day Schedule", "Payroll",
         "When salary is paid, holidays and weekends around pay day, what to do if salary is late, changing your salary bank account."),
    _pay("tax-declaration", "Income Tax Declaration and Proofs", "Tax",
         "Old vs new regime, investment declaration window, proof submission, Form 16, common deductions."),
    _pay("salary-structure", "Salary Structure Explained", "Compensation",
         "CTC components: basic, HRA, special allowance, PF, gratuity, bonus; gross vs net pay."),
    _pay("stock-options", "Employee Stock Options (ESOP) and Vesting", "Equity",
         "Grants, vesting schedule and cliff, exercising options, leaving the company, tax at exercise, EquityPortal."),
    _pay("payslips", "Payslips and Payroll Corrections", "Payroll",
         "Downloading payslips from PeopleHub, reading each line of the payslip, reporting an incorrect salary or deduction, arrears and corrections."),
)

GAPS: tuple[Gap, ...] = (
    Gap("monitor-flickering", "External monitor or laptop display flickering, flashing or showing lines",
        re.compile(r"\bmonitors?\b|\bflicker|\bdisplay (?:issue|problem)s?\b", re.I)),
    Gap("office-parking", "Office car or bike parking, parking passes and spaces",
        re.compile(r"\bparking\b", re.I)),
    Gap("printers", "Printers, printing, scanners and print queues",
        re.compile(r"\bprint(?:er|ers|ing)\b|\bscanners?\b|\bprint queues?\b", re.I)),
    Gap("cafeteria", "Office cafeteria, canteen, meal coupons and snacks",
        re.compile(r"\bcafeteria\b|\bcanteen\b|\bpantry\b|\bmeal (?:coupon|card|voucher)s?\b|\bsnacks?\b", re.I)),
    Gap("office-shuttle", "Office shuttle, company cab or bus transport",
        re.compile(r"\bshuttle\b|\b(?:office|company) (?:cab|bus|transport)\b|\bcab (?:service|facility)\b", re.I)),
    Gap("relocation", "Relocation assistance, moving allowance and transfers between cities",
        re.compile(r"\brelocat", re.I)),
    Gap("sabbatical", "Sabbatical or long unpaid career breaks",
        re.compile(r"\bsabbatical|\bcareer break", re.I)),
)


def find_gap_mentions(text: str) -> list[str]:
    """Gap ids whose forbidden terms appear in `text`."""
    return [gap.gap_id for gap in GAPS if gap.forbidden.search(text)]
