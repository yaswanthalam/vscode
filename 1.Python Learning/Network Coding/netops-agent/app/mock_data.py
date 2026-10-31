"""Canned data for NETOPS_MOCK=true so the GUI and agent can be demoed
without devices, Kusto or Azure OpenAI.

Scenario: rtr-lab-01 was downgraded 7.9.2 -> 7.5.2 on 2026-10-20 by 'jdoe'.
sw-lab-02 has NO OS events in Kusto, so the agent has to fall back to the device.
"""

_KUSTO = {
    ("device_os_version", "rtr-lab-01"): [
        {"DeviceName": "rtr-lab-01", "OsVersion": "7.9.2", "FirstSeen": "2026-07-29T00:00:00Z", "LastSeen": "2026-10-20T03:00:00Z"},
        {"DeviceName": "rtr-lab-01", "OsVersion": "7.5.2", "FirstSeen": "2026-10-20T03:30:00Z", "LastSeen": "2026-10-27T17:00:00Z"},
    ],
    ("os_change_events", "rtr-lab-01"): [
        {"Timestamp": "2026-10-20T03:22:41Z", "DeviceName": "rtr-lab-01", "Severity": "notice", "Message": "%PKT_INFRA-FM-6-FAULT_INFO : Router reload after install operation 41"},
        {"Timestamp": "2026-10-20T03:14:05Z", "DeviceName": "rtr-lab-01", "Severity": "notice", "Message": "%INSTALL-INSTMGR-6-OPERATION_SUCCESS : Install operation 41 (install activate 7.5.2) by user 'jdoe' completed"},
        {"Timestamp": "2026-10-20T03:02:10Z", "DeviceName": "rtr-lab-01", "Severity": "info", "Message": "%INSTALL-INSTMGR-6-OPERATION_START : Install operation 41 started by jdoe: install replace harddisk:/xrv9k-7.5.2.iso"},
    ],
    ("who_ran_commands", "rtr-lab-01"): [
        {"Timestamp": "2026-10-20T02:58:12Z", "DeviceName": "rtr-lab-01", "UserName": "jdoe", "SourceIp": "10.20.1.15", "Command": "show install active"},
        {"Timestamp": "2026-10-20T03:02:09Z", "DeviceName": "rtr-lab-01", "UserName": "jdoe", "SourceIp": "10.20.1.15", "Command": "install replace harddisk:/xrv9k-7.5.2.iso"},
        {"Timestamp": "2026-10-20T03:13:50Z", "DeviceName": "rtr-lab-01", "UserName": "jdoe", "SourceIp": "10.20.1.15", "Command": "install commit"},
    ],
}

_DEVICE = {
    "show version": {
        "cisco_xr": "Cisco IOS XR Software, Version 7.5.2\nCopyright (c) 2013-2022 by Cisco Systems, Inc.\n\nBuild Information:\n Built By     : ingunawa\n Built On     : Tue Jun 14 2022\n\ncisco XRv9K Virtual Router\nSystem uptime is 7 days 13 hours 52 minutes",
        "arista_eos": "Arista DCS-7280SR3-48YC8\nHardware version: 11.02\nSerial number: JPE21000000\n\nSoftware image version: 4.28.3M\nArchitecture: x86_64\nInternal build version: 4.28.3M-29204934.4283M\nUptime: 2 days, 4 hours and 10 minutes",
        "juniper_junos": "Hostname: mx-lab-03\nModel: mx204\nJunos: 21.4R3-S5.4\n",
    },
    "show lacp summary": {
        "cisco_xr": "Bundle-Ether10 is up, 2 of 2 members active\n  Hu0/0/0/0  Active  Fast  Collecting,Distributing\n  Hu0/0/0/1  Active  Fast  Collecting,Distributing",
        "arista_eos": "Port Channel Port-Channel10:\n Et1  Bundled  Active  Fast\n Et2  Bundled  Active  Fast",
        "juniper_junos": "Aggregated interface: ae0\n  xe-0/0/0  Actor  Active  Fast  Collecting distributing\n  xe-0/0/1  Actor  Active  Fast  Collecting distributing",
    },
    "show isis neighbors": {
        "cisco_xr": "IS-IS core neighbors:\nSystem Id      Interface        SNPA           State Holdtime Type IETF-NSF\nsw-lab-02      BE10             *PtoP*         Up    24       L2   Capable\nmx-lab-03      Hu0/0/0/2        *PtoP*         Up    27       L2   Capable",
        "arista_eos": "Instance  VRF      System Id        Type Interface   SNPA   State Hold time\ncore      default  rtr-lab-01       L2   Po10        P2P    UP    28",
        "juniper_junos": "Interface    System         L State   Hold (secs) SNPA\net-0/0/2.0   rtr-lab-01     2  Up                   25",
    },
    "show logging": {
        "cisco_xr": "RP/0/RP0/CPU0:Oct 20 03:14:05 : instmgr[1234]: %INSTALL-INSTMGR-6-OPERATION_SUCCESS : Install operation 41 by jdoe completed",
        "arista_eos": "Oct 25 09:41:12 sw-lab-02 SuperServer: %SYS-5-CONFIG_I: Configured from console by admin2 on vty3 (10.20.1.44)\nOct 25 09:44:03 sw-lab-02 Launcher: %SYS-5-SYSTEM_RELOADED: System reloaded. Boot image flash:/EOS-4.28.3M.swi (previous EOS-4.30.1F.swi)\nOct 25 09:40:57 sw-lab-02 Aaa: %AAA-6-EXEC_CMD: user admin2 ran 'install source flash:EOS-4.28.3M.swi' ",
        "juniper_junos": "Oct 22 11:00:01 mx-lab-03 mgd[2211]: UI_CMDLINE_READ_LINE: User 'ops1', command 'show system uptime'",
    },
    "show running-config": {
        "cisco_xr": "hostname rtr-lab-01\nusername netops\n secret 10 $6$abcdEFGH$hashedvalue\nrouter isis core\n is-type level-2-only",
    },
}


def kusto(template: str, params: dict) -> list[dict]:
    return list(_KUSTO.get((template, params.get("device")), []))


def device(name: str, platform: str, command: str) -> str:
    base = command.split("|")[0].strip().lower()
    for key, by_platform in _DEVICE.items():
        if base.startswith(key):
            out = by_platform.get(platform, by_platform.get("cisco_xr", ""))
            if "|" in command and command.split("|")[1].strip().startswith(("include", "match", "grep")):
                needle = command.split("|")[1].split(None, 1)[1].strip().lower()
                out = "\n".join(l for l in out.splitlines() if needle in l.lower())
            return out
    return f"% (mock) no canned output for '{command}' on {name}"
