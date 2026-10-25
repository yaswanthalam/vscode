# Deterministic demo (no AI model used)

## Observations
- [L1] 2026-10-22T10:01:02Z lab-router Interface Ethernet1 changed state to down
- [L2] 2026-10-22T10:01:05Z lab-router BGP neighbor 192.0.2.2 changed state to Idle
- [L3] 2026-10-22T10:02:00Z lab-router Interface Ethernet1 changed state to up
- [L4] 2026-10-22T10:02:15Z lab-router BGP neighbor 192.0.2.2 changed state to Established

## Possible causes
Insufficient evidence to confirm a root cause.

## Missing evidence
Current device state, topology, vendor/OS, and surrounding logs.

## Next checks
- Check current BGP neighbor state and last reset reason.
- Check reachability and route to the peer in the correct VRF.
- Compare local and remote logs, timers, and transport errors.
- Check current interface operational and administrative state.
- Inspect error counters, optical levels, and remote-end status.
- Confirm which neighbors and routes use this interface.