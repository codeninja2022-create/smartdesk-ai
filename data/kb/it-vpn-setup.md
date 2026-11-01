---
doc_id: it-vpn-setup
title: VPN Setup for Remote Work
domain: IT
category: IT Support
subcategory: Network
provenance:
  source_type: dataset_derived
  datasets:
  - Console-AI/IT-helpdesk-synthetic-tickets@165693849d95
  source_record_ids:
  - it_tickets:3iclill17
  - it_tickets:g5ox12x1v
  - it_tickets:jdy0itrhg
  - it_tickets:eu047v7pl
  generator_model: gpt-4o-mini
  generated_at: '2026-10-31'
---
# VPN Setup for Remote Work

This article provides detailed instructions for setting up and connecting to the Cisco Secure Client VPN for secure remote work at NovaTech Solutions. It covers installation steps for Windows, macOS, and Linux, as well as who needs VPN access and connection procedures.

## Who Needs VPN Access?

Employees who need to access internal systems and resources from outside the office must use the VPN. This includes:

1. Remote workers accessing company applications.
2. Employees working from home or other locations outside the office.
3. Any staff member needing secure access to sensitive company data.

## Installing Cisco Secure Client

### For Windows:
1. Open the Software Center on your Windows laptop.
2. Search for "Cisco Secure Client" in the application list.
3. Click on the application and select "Install."
4. Wait for the installation to complete.

### For macOS:
1. Open the Self Service application on your Mac.
2. Find "Cisco Secure Client" in the list of available applications.
3. Click "Install" and wait for the process to finish.

### For Linux:
1. Download the Cisco Secure Client package from the official Cisco website (ensure you have the correct version for your distribution).
2. Open a terminal and navigate to the directory where the package is downloaded.
3. Use the package manager to install it (e.g., `sudo dpkg -i <package_name>.deb` for Debian-based systems or `sudo rpm -i <package_name>.rpm` for Red Hat-based systems). 
4. Follow any additional on-screen instructions to complete the installation.

## Connecting to the VPN

### Connection Steps:
1. Open the Cisco Secure Client application on your device.
2. Enter the VPN gateway address: `vpn.novatech.example`.
3. Click on "Connect."
4. You will be prompted to enter your Okta credentials (username and password).
5. Complete the Multi-Factor Authentication (MFA) using Okta Verify (push notification or 6-digit code).
6. Once authenticated, you will be connected to the VPN and can access internal systems.

## Frequently asked questions

### How do I know if I need VPN access?

If you need to access internal company systems or resources while working remotely, you will need VPN access.

### What should I do if I encounter issues while installing Cisco Secure Client?

If you face issues during installation, please contact the IT Service Desk via ServiceHub or email itsupport@novatech.example for assistance.

### Can I connect to the VPN from my personal devices?

Yes, you can connect to the VPN from personal devices, but ensure you follow the installation and connection steps outlined in this article.

### What if I forget my Okta password while trying to connect to the VPN?

If you forget your Okta password, you can reset it using the Password portal at https://passwords.novatech.example.

### Is there a limit to the number of devices I can connect to the VPN?

There is no specific limit to the number of devices you can connect to the VPN, but ensure that you comply with company security policies.
