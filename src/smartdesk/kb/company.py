"""Canonical facts about the fictional company.

Every generated document is written against this one fact sheet, so numbers,
system names and contacts agree across the whole knowledge base.
"""

COMPANY_NAME = "NovaTech Solutions"

COMPANY_PROFILE = """\
Company: NovaTech Solutions, a 500-employee B2B SaaS company headquartered in \
Bengaluru, India (office: Outer Ring Road, Bellandur). Currency: INR. \
Working week: Monday to Friday, core hours 11:00-16:00 IST.

Internal systems:
- ServiceHub (https://servicehub.novatech.example): IT and HR self-service portal \
for requests and incidents.
- PeopleHub (https://peoplehub.novatech.example): HRMS for leave, payslips, \
expenses, tax declarations and benefits.
- Password portal: https://passwords.novatech.example (self-service reset and unlock).
- Identity: Okta single sign-on for all cloud apps; MFA via Okta Verify \
(push or 6-digit code). Hardware security keys (YubiKey) for admins.
- VPN: Cisco Secure Client (AnyConnect), gateway vpn.novatech.example; \
required for internal systems from outside the office.
- Email and calendar: Microsoft 365 (Outlook, Teams, OneDrive, SharePoint).
- Software Center (Windows) and Self Service (macOS) for pre-approved apps.
- Corporate Wi-Fi SSID "NovaTech-Corp" (802.1X, Okta credentials); \
guest Wi-Fi SSID "NovaTech-Guest" (daily voucher from reception, valid 24 hours).

Contacts:
- IT Service Desk: ServiceHub, email itsupport@novatech.example, phone ext. 2020; \
staffed 08:00-20:00 IST Monday to Friday; P1 outages 24x7 via ext. 2020.
- HR Help Desk: ServiceHub (HR category), email hr@novatech.example, ext. 3030; \
09:30-18:30 IST Monday to Friday.
- Payroll team: payroll@novatech.example.
- Ethics and whistleblower line: ethics@novatech.example (can be anonymous).
- Internal Committee (POSH): ic@novatech.example.

HR facts:
- Leave year: January to December. Casual leave 12 days/year (no carry-forward, \
no encashment, max 3 consecutive days). Sick leave 8 days/year (medical \
certificate for more than 2 consecutive days, no encashment). Earned leave \
15 days/year (accrues 1.25 days/month, carry-forward up to 30 days, encashable \
on exit). Maternity leave 26 weeks. Paternity leave 2 weeks within 3 months of \
birth/adoption. Compensatory off for approved weekend/holiday work, used within \
60 days. Leave applied and approved in PeopleHub.
- Public holidays: 12 fixed per year plus 2 floating holidays from the \
published list.
- Hybrid work: 3 office days per week (Tuesday-Thursday anchor days); up to \
10 extra full-remote days per quarter with manager approval; fully remote \
roles by exception approved by HR and the department head.
- Expense reimbursement: submit in PeopleHub Expenses within 30 days with \
receipts; manager approval, then Finance review; paid with the next payroll \
run. Monthly internet allowance INR 1,500 for hybrid employees.
- Performance: half-yearly reviews (April and October); goals set in PeopleHub; \
5-point rating scale; annual increments effective 1 April.
- Probation: 6 months, confirmed by manager review; notice period 30 days \
during probation, 60 days after confirmation.
- Learning budget: INR 25,000 per employee per financial year.
- Group health insurance: INR 5 lakh family floater (employee, spouse, \
2 children; parents optional at employee cost); enrol within 30 days of \
joining in PeopleHub Benefits; insurer TPA card issued within 15 days. \
Group term life cover 3x annual CTC.

Onboarding facts:
- Day one starts 09:30 at the Bellandur office reception; HR induction, \
laptop handover, ID badge, Okta and MFA setup.
- Laptop: MacBook Pro 14" (engineering/design) or Dell Latitude 7450 \
(other roles), ready on day one; requested by the hiring manager 10 working \
days before the start date.
- Buddy programme: every new joiner gets a buddy for the first 90 days.

Payroll facts:
- Pay day: last working day of each month; payslips in PeopleHub by the \
1st of the next month.
- Financial year April-March. Investment declaration in PeopleHub by \
30 April; proof submission 1-31 January; choose old or new tax regime at \
declaration; Form 16 issued by 15 June.
- Salary structure: basic 40% of CTC, HRA 50% of basic, special allowance, \
employer PF 12% of basic, gratuity per statute, annual performance bonus \
up to 10% of CTC.
- ESOPs: 4-year vesting with a 1-year cliff (25% at the first anniversary, \
then quarterly), exercise window 7 years from grant, managed in the \
EquityPortal (https://equity.novatech.example)."""
