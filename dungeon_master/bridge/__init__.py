"""The device-facing side of the game.

A small HTTP server on the LAN that a microcontroller can talk to. It exists
because an ESP32 cannot sensibly be a Catalyst client: there is no Dapr SDK for
it, speaking the Dapr HTTP API directly would mean putting a long-lived
`dapr-api-token` in firmware, and TLS on the device costs tens of KB of RAM it
would rather spend on a framebuffer.

It costs nothing to add, because the workflow worker already has to run on this
machine. The bridge is a second endpoint on a process that was required anyway.

What it does that the device cannot:

  * holds the Catalyst credential, so the device holds none;
  * reshapes a scene for a 240x320 screen. The terminal client renders ~600+
    characters per scene; a readable 16px font on that panel holds about 384.
    So the bridge pre-wraps the text and decides what to drop -- see layout.py;
  * absorbs the per-turn latency, so the device makes one request and gets one
    answer.
"""
