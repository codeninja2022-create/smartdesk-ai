---
doc_id: it-vpn-troubleshooting
title: VPN Troubleshooting
domain: IT
category: IT Support
subcategory: Network
provenance:
  source_type: dataset_derived
  datasets:
  - Console-AI/IT-helpdesk-synthetic-tickets@165693849d95
  source_record_ids:
  - it_tickets:gixitb6w4
  - it_tickets:il7fw6is3
  - it_tickets:jlm61eonw
  - it_tickets:oyzx28mhf
  - it_tickets:cjt8t5scv
  - it_tickets:jmm69mpwo
  - it_tickets:bdrby5ar2
  - it_tickets:4q06jbf94
  generator_model: gpt-4o-mini
  generated_at: '2026-10-31'
---
# VPN Troubleshooting

This article provides troubleshooting steps for common VPN issues encountered by employees at NovaTech Solutions, including connection errors, authentication failures, frequent disconnections, and slow performance. It also outlines what information to include when escalating VPN-related issues to the IT Service Desk.

## Common VPN Errors and Fixes

1. **Cannot Connect**  
   - **Check Internet Connection**: Ensure you have a stable internet connection. Try accessing a website to confirm.
   - **Verify VPN Credentials**: Double-check your username and password. Ensure there are no typos.
   - **Restart VPN Client**: Close and reopen the Cisco Secure Client (AnyConnect) to refresh the connection.
   - **Reboot Device**: Restart your computer to clear any temporary issues.
   - **Firewall/Antivirus Settings**: Ensure that your firewall or antivirus software is not blocking the VPN connection.

2. **Authentication Failed**  
   - **Check Credentials**: Confirm that you are using the correct username and password.
   - **MFA Issues**: If using Okta Verify for multi-factor authentication, ensure you are receiving the push notification or entering the correct 6-digit code.
   - **Account Lockout**: If you have attempted to log in multiple times unsuccessfully, your account may be locked. Contact IT for assistance.

3. **Frequent Drops**  
   - **Network Stability**: Check your internet connection for stability. Consider switching to a wired connection if using Wi-Fi.
   - **VPN Settings**: Ensure that the VPN settings are correctly configured. Revisit the setup instructions provided during onboarding.
   - **Update VPN Client**: Ensure that you are using the latest version of the Cisco Secure Client. Check for updates and install if necessary.

4. **Slow Over VPN**  
   - **Check Bandwidth**: Run a speed test to determine your internet speed. If slow, try disconnecting other devices from the network.
   - **Server Location**: If possible, connect to a different VPN server location that may offer better performance.
   - **Reduce Load**: Limit the number of applications running that require internet access while using the VPN.

## Escalation Information

When escalating a VPN issue to the IT Service Desk, please include the following information to assist in troubleshooting:
1. **Description of the Issue**: A clear and concise description of the problem you are experiencing.
2. **Error Messages**: Any specific error messages displayed by the VPN client.
3. **Steps Taken**: A list of troubleshooting steps you have already attempted.
4. **Device Information**: The type of device you are using (e.g., company-issued laptop, OS version).
5. **Network Environment**: Whether you are connecting from the office or remotely, and if remotely, the type of internet connection (e.g., home Wi-Fi, mobile data).
6. **Screenshots**: If applicable, include screenshots of error messages or configurations.

## Contact IT for Further Assistance

If the troubleshooting steps above do not resolve your VPN issues, please contact the IT Service Desk for further assistance:
- **Email**: itsupport@novatech.example  
- **Phone**: ext. 2020  
- **Hours**: 08:00-20:00 IST Monday to Friday; for P1 outages, available 24x7 via ext. 2020.

## Frequently asked questions

### What should I do if I cannot connect to the VPN?

Check your internet connection, verify your VPN credentials, restart the VPN client, and reboot your device. If the issue persists, check your firewall or antivirus settings.

### Why am I receiving an authentication failed error when connecting to the VPN?

Ensure you are using the correct username and password. If using multi-factor authentication, check that you are entering the correct code from Okta Verify.

### What can I do if my VPN connection keeps dropping?

Check your internet stability, ensure your VPN settings are correct, and update your VPN client to the latest version.

### How can I improve slow performance while using the VPN?

Check your internet bandwidth, try connecting to a different VPN server location, and limit the number of applications using the internet while connected.

### What information should I provide when escalating a VPN issue to IT?

Include a description of the issue, any error messages, steps taken to troubleshoot, device information, network environment, and screenshots if applicable.
