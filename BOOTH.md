# Booth checklist

How to run the device edition at an event: the ESP32 boards, the bridge on a
laptop, and a GL.iNet Beryl AX (GL-MT3000) travel router carrying the network.

The point of the router: **the network travels with the kit.** The boards, the
laptop and the bridge see the same SSID, password and addresses at the booth as
on the desk. The only thing that changes at a venue is how the router reaches
the internet — and the bridge needs that, because the save file is a workflow
history in Catalyst.

Venue Wi-Fi alone is not a substitute. Guest networks usually isolate clients
(the board can never reach the laptop), put up a captive portal (the board
cannot click "I agree"), or are 5GHz only (the board is 2.4GHz only).

## Before you leave

- [ ] `firmware/cyd/include/secrets.h` has the Beryl's SSID and password, and
      `BRIDGE_HOST` is the laptop's address on the Beryl (`192.168.8.x`).
- [ ] The laptop's address is reserved on the router: `http://192.168.8.1` →
      Network → LAN → Address Reservation. Use the MAC the laptop shows on
      that network (`ifconfig en0 | awk '/ether/{print $2}'`). On a Mac, set
      System Settings → Wi-Fi → Details → Private Wi-Fi address to **Fixed**
      first, or the MAC can rotate and the reservation stops matching.
- [ ] Every board flashed from the same build. Slots derive from each chip, so
      no per-board build. Each one shows `wifi ok` then `bridge ok`.
- [ ] Laptop auto-joins **only** the router. System Settings → Wi-Fi → Details
      → Auto-Join off for every other known network. Otherwise, the moment the
      router loses its uplink, the laptop jumps to another network and every
      board says "is the bridge running?".
- [ ] Dry run at home on the phone uplink only, with the home network out of
      the path. Check with `curl -s https://ipinfo.io/org`: it should name the
      mobile carrier, not the home ISP.
- [ ] `DM_REST_SECONDS` in `.env` under 60. A longer rest outlasts the board's
      request timeout (`HTTPClient::setTimeout` is a `uint16_t`).

**Pack:** the router and its USB-C supply (5V/3A), the boards and cables, a USB
hub or battery for them, a phone cable for tethering, the laptop charger.

## At the booth, in this order

1. **Power the router.** The laptop rejoins its network on its own.
2. **Give the router an uplink.** `http://192.168.8.1` → **Internet**:
   - **Phone** (recommended), either way:
     - *USB tethering*: phone into the router's USB-A port with a **data**
       cable, then Personal Hotspot (iPhone) or USB tethering (Android) on.
       On Android the option is grayed out until the phone sees a data
       connection — a charge-only cable looks exactly like that.
     - *Phone hotspot + Repeater*: no cable needed. Hotspot on, router →
       Repeater → join the phone. Turn **Wi-Fi off on the phone**, or some
       Android phones share the Wi-Fi they're on instead of mobile data.

     Independent of the venue and of any captive portal.
   - **Repeater**: join the venue Wi-Fi. If it has a captive portal, open any
     page on the laptop to accept it once. The Beryl can repeat 5GHz.
   - **Ethernet** into the WAN port, if the booth has a drop.
3. **Keep the laptop awake.** If it sleeps, the bridge and the workflow worker
   sleep with it.
   ```sh
   caffeinate -dis &
   ```
4. **Start the bridge** from the repo root:
   ```sh
   uv run --extra workflow python -m dungeon_master.bridge.server
   ```
5. **Prove it end to end.** `/ping` proves the bridge; `/scene` proves the uplink.
   ```sh
   curl -s localhost:8080/ping
   curl -s "localhost:8080/scene?slot=cyd-1" | head -c 80
   ```
   `upstream unavailable` from `/scene` means the uplink, not the board.
6. **Power the boards.** Each shows `wifi ok`, `bridge ok`, then its scene.
   Boards go on **last**: changing the router's uplink restarts its Wi-Fi, and a
   board that drops off may not rejoin by itself. If you change the uplink
   during the day, power-cycle the boards afterwards.

## When something breaks

| Board shows | Meaning | Fix |
|---|---|---|
| `wifi FAIL` / "check 2.4GHz SSID" | Can't join the router | Check the router is up. Do not reflash. The serial log prints a reason code: 15/204 is usually the password, 201 the SSID not seen. |
| "is the bridge running?" | Joined, but can't reach the laptop | Check the **laptop's** Wi-Fi first: it is usually on another network. Then: bridge running (step 4)? |
| Board on nothing after an uplink change | The router restarted its Wi-Fi and the board didn't rejoin | Power-cycle the board. |
| Taps do nothing, screen holds | The uplink dropped | Router → Internet; switch to the phone. The bridge serves the last screen until Catalyst answers again. |

## Two rules for the day

- **Never restart the bridge while people are playing.** It hosts the workflow
  worker, so every adventure on every board stalls until it is back.
- **To show a run** (the raffle): the run id is in the HUD of the board's map
  screen — tap the title bar. Open
  `https://catalyst.diagrid.io/workflows/dungeon-master/<runId>?project=dungeon-master`.
  The project goes in `?project=` by name; the wrong parameter silently shows
  the default project.
