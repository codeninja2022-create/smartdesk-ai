---
doc_id: it-remote-desktop
title: Remote Desktop Access
domain: IT
category: IT Support
subcategory: Network
provenance:
  source_type: dataset_derived
  datasets:
  - Console-AI/IT-helpdesk-synthetic-tickets@165693849d95
  source_record_ids:
  - it_tickets:arztwej7e
  - it_tickets:0f4son7ut
  - it_tickets:nbshemzya
  - it_tickets:upov2bl5v
  - it_tickets:8y8rmt8sl
  - it_tickets:cg6f0mvu7
  - it_tickets:tbxt0zeiu
  - it_tickets:2r030ppqb
  generator_model: gpt-4o-mini
  generated_at: '2026-10-31'
---
# Remote Desktop Access

This article provides guidance on remote desktop access at NovaTech Solutions, including when it is permitted, how to request access, connecting via VPN, and troubleshooting common connection errors.

## When Remote Desktop Access is Allowed

Remote desktop access is permitted for employees who need to work remotely while maintaining secure access to company resources. This includes:

1. **Hybrid Work**: Employees working from home on designated remote days.
2. **Business Continuity**: Employees needing access during unexpected office closures or emergencies.
3. **Manager Approval**: Ensure you have your manager's approval for remote work and access.

## Requesting Remote Desktop Access

To request remote desktop access, follow these steps:

1. **Submit a Request**: Go to the IT self-service portal at [ServiceHub](https://servicehub.novatech.example).
2. **Select IT Support**: Choose the IT support category.
3. **Fill Out the Form**: Provide your details, including your employee ID and the reason for access.
4. **Await Approval**: Your request will be reviewed by the IT team, and you will be notified once access is granted.

## Connecting Over VPN

To connect to the remote desktop, you must first establish a VPN connection. Here’s how:

1. **Install Cisco Secure Client**: Ensure you have the Cisco Secure Client (AnyConnect) installed on your device.
2. **Launch Cisco Secure Client**: Open the application.
3. **Connect to VPN**: Enter the gateway address: `vpn.novatech.example` and your Okta credentials.
4. **Verify Connection**: Ensure the VPN connection is established before attempting to connect to the remote desktop.

## Common Connection Errors and Troubleshooting

If you encounter issues while connecting to the remote desktop, consider the following troubleshooting steps:

1. **Check VPN Connection**: Ensure you are connected to the VPN. If not, reconnect and try again.
2. **Verify Remote Desktop Settings**: Ensure that the remote desktop settings on your local machine match the required configurations.
3. **Authentication Issues**: If you experience authentication failures, verify your Okta credentials and ensure you are using multi-factor authentication (MFA).
4. **Screen Resolution Problems**: Adjust the display settings on your local machine to match the remote desktop's resolution. You can also check for updates or patches that may resolve display scaling issues.
5. **File Transfer Issues**: If you are unable to transfer files, ensure that the remote desktop settings allow file sharing. Check your local and remote desktop configurations for any restrictions.

## Frequently asked questions

### How do I request remote desktop access?

To request remote desktop access, submit a request through the IT self-service portal (ServiceHub) under the IT support category.

### What should I do if I cannot connect to the remote desktop?

First, ensure you are connected to the VPN. If the VPN is connected and you still cannot access the remote desktop, check your remote desktop settings and verify your Okta credentials.

### Is remote desktop access allowed for personal devices?

Yes, remote desktop access is allowed on personal devices, provided you have received the necessary approval from your manager and have configured your device correctly.

### What are the common issues with remote desktop connections?

Common issues include VPN connection failures, authentication errors, screen resolution problems, and difficulties with file transfers. Refer to the troubleshooting section for detailed steps.

### Can I use remote desktop access from outside the office?

Yes, you can use remote desktop access from outside the office, but you must connect through the VPN first.
