---
name: circuit-designer
description: >
  Design complete electronic circuits from a product idea — from "I want a thing that does X"
  through block diagrams, topology selection, component calculations, and a full schematic with
  values. This is the engineering phase that happens BEFORE opening EasyEDA or any PCB tool.
  Claude acts as the circuit designer: given requirements, it proposes the full topology, selects
  components, calculates values, and produces a parts list ready for implementation.
  
  Use this skill whenever the user describes a product idea or function they want to build
  electronically, asks "design me a circuit that...", wants to go from concept to schematic,
  mentions transmitters, receivers, sensors, motor controllers, power supplies, amplifiers,
  or any electronics project where the circuit doesn't exist yet. Also trigger when the user
  says things like "I want to build a thing that...", "how would I make a device that...",
  "design the electronics for...", or "what circuit do I need for...". This skill handles
  the creative engineering — the downstream easyeda-design-assistant skill handles PCB
  implementation.
---

# Circuit Designer

Design complete electronic circuits from a product idea. This skill takes you from
"I want a thing that does X" to a fully specified schematic with component values,
ready for PCB implementation.

## The V-Model: Design Is Not a Waterfall

Hardware design flows downstream (idea → circuit → parts → PCB → manufacturing) but
constantly loops back upstream when reality intrudes. This is normal and expected.

```
  Idea / Requirements
      ↕
  Block Diagram / Architecture
      ↕
  Circuit Topology & Calculations
      ↕
  Component Selection + Netlist JSON
      ↕
  ★ generate-schematic (auto-generates EasyEDA JSON from netlist)
      ↕
  easyeda-design-assistant (refinement + footprint linking + PCB prep)
      ↕
  PCB Layout & Manufacturing
```

Every arrow is bidirectional. Common backtrack triggers:

- **Part unavailable or EOL** → revisit component selection, possibly topology
- **Footprint too large for board** → different package, possibly different part
- **JLCPCB doesn't stock the part** → find LCSC alternative, update circuit if values change
- **PCB layout reveals signal integrity issue** → rethink topology or add filtering
- **Cost too high** → simplify circuit, use integrated module instead of discrete
- **Testing reveals performance gap** → adjust values, add stages, change topology

When any of these happen, come back to the relevant phase in this skill and rework.
The parts map (the shared table of components) is what ties the phases together —
update it here, and the downstream skills pick up the changes.

---

## Phase 0: Understand the Product Idea

Before designing anything, extract the real requirements. This interview phase is
where you prevent the most expensive mistakes. Every question you don't ask here
becomes a redesign cycle later. Be thorough — it's much cheaper to spend 10 minutes
asking questions than to redesign a circuit after discovering the user wanted
something different.

**Do not start designing until you have clear answers to all sections below.**
If the user gives a vague answer ("it should be fast" or "battery powered"), push
for specifics. Vague requirements produce wrong designs.

### Functional Requirements

- **What does it need to do?** (transmit a signal, sense temperature, drive a motor, etc.)
- **What triggers the action?** (button press, sensor threshold, timer, remote command)
- **What's the output?** (LED, buzzer, relay, wireless signal, data to a computer)
- **Momentary or latching?** (Does the output stay on after the trigger, or only while
  triggered? This single question prevents one of the most common redesign cycles.)
- **How far / how fast / how accurate?** (range, speed, precision — the performance envelope)
- **Multiple channels / devices?** (One button one action? Or multiple buttons each
  triggering different things? This affects addressing, encoding, and complexity.)
- **Feedback to the user?** (Does the user need to know it worked? LED confirmation,
  buzzer acknowledgment, display feedback?)
- **What happens on failure?** (If the battery dies, if the signal is lost, if the
  sensor reads out of range — fail safe? fail silent? alarm?)

### Environmental Constraints

- **Power source**: Battery (what voltage? rechargeable?), USB, wall adapter, solar?
- **How long on a charge?** (days? months? always-on? This drives the entire power
  budget and may rule out certain topologies.)
- **Size constraints**: Must fit in a specific enclosure? Wearable? Desktop?
- **Operating environment**: Indoor, outdoor, high-temp, wet, vibration?
- **Regulatory**: Does it transmit RF? (FCC/CE considerations — modules with
  pre-certification are vastly easier)

### User Interaction Model

This is often overlooked but matters enormously:
- **Who will use this device?** (the builder? a family member? a customer?)
- **How technical is the end user?** (Can they solder? Program? Or is this
  a finished product that "just works"?)
- **What physical controls?** (buttons, switches, knobs, touchscreen, phone app?)
- **What physical indicators?** (LEDs, display, speaker, nothing?)
- **Enclosure?** (off-the-shelf box, 3D printed, none/bare PCB?)

### Manufacturing Intent

- **Prototype only** → hand-solder, through-hole, perfboard/breadboard OK
- **Small run** (10-100 units) → PCB from JLCPCB, mix of SMD and TH
- **Production** (100+) → full SMD, JLCPCB assembly, cost-optimized BOM

### Budget and Timeline

- **Component budget per unit**: $5? $20? $100?
- **How soon**: Prototype this weekend? Production in 3 months?

These answers drive every downstream decision. A battery-powered, hand-soldered prototype
of a wireless button needs completely different design choices than a production-ready
module going into 1000 units.

### Confirm Understanding Before Proceeding

After gathering requirements, restate them back to the user in a brief summary:
"So you want [X] that does [Y] when [Z], powered by [W], and it needs to [specific
behavior]. Is that right, or did I miss anything?"

Do not proceed to Phase 1 until the user confirms.

---

## Phase 1: Block Diagram

Break the product into functional blocks. Every electronics project decomposes into
a signal chain of blocks, each with a clear input and output.

### Common Block Types

**Signal sources** (where information enters the system):
- Sensors (temperature, light, motion, pressure, magnetic)
- User input (buttons, switches, potentiometers, encoders, touchscreens)
- Communication receivers (RF, IR, UART, SPI, I2C, USB)
- Timing (oscillators, crystals, RTC modules)

**Processing** (where decisions happen):
- Microcontrollers (MCU) — for programmable logic
- Discrete logic (gates, flip-flops) — for simple fixed logic
- Analog processing (comparators, op-amp circuits) — for threshold detection, filtering
- No processing at all — direct signal path (simpler, more robust)

**Signal conditioning** (between blocks):
- Amplifiers (boost weak signals)
- Filters (remove noise, select frequency bands)
- Level shifters (match voltages between blocks)
- ADC/DAC (bridge analog and digital domains)

**Output / actuation** (where the system affects the world):
- Drivers (transistor switches, H-bridges, relay drivers)
- Communication transmitters (RF, IR, UART, USB)
- Indicators (LEDs, displays, buzzers)
- Power delivery (voltage regulators, battery chargers)

**Power supply** (every project needs this):
- Voltage regulation (linear or switching)
- Battery management (if battery-powered)
- Decoupling and filtering

### Drawing the Block Diagram

For each block, specify:
1. **What it does** (one sentence)
2. **Input signal** (type, voltage range, frequency)
3. **Output signal** (type, voltage range, frequency)
4. **Power requirement** (voltage, current draw estimate)

Connect blocks in signal flow order. Label every connection with signal type and level.

### Example: Wireless Button → Remote Action

```
[Button] → [Debounce] → [Encoder/MCU] → [RF Transmitter] ~~~air~~~
                                                                    
[RF Receiver] → [Decoder/MCU] → [Output Driver] → [Relay/LED/Buzzer]

Power: Battery (TX side), USB or wall adapter (RX side)
```

Blocks identified:
- Button + debounce (simple RC or Schmitt trigger)
- Encoder or MCU (generates coded signal)
- RF TX module (sends signal wirelessly)
- RF RX module (receives signal)
- Decoder or MCU (interprets coded signal)
- Output driver (switches a load)
- Power supply (both sides)

---

## Phase 2: Topology Selection

For each block, choose the implementation approach. This is where the major
architecture decisions happen.

### The Module vs. Discrete Decision

This is often the most impactful choice in the entire design:

**Use a module when:**
- RF/wireless (pre-certified modules save months of FCC work)
- Complex protocols (WiFi, Bluetooth, LoRa, Zigbee)
- First prototype (get it working, optimize later)
- Cost is not the primary constraint
- You're not an RF engineer (and that's fine)

**Use discrete components when:**
- Simple, well-understood circuits (amplifiers, filters, power supplies)
- Cost must be minimized for production
- Educational purpose (you want to understand the internals)
- The required function is too simple to justify a module (e.g., a transistor switch)
- Specific performance requirements that modules can't meet

**Common modules that replace complex discrete designs:**
- nRF24L01+ → 2.4GHz transceiver (replaces entire RF frontend)
- HC-12 / HC-05 → serial wireless link (replaces RF + protocol stack)
- ESP32 / ESP8266 → WiFi + MCU (replaces MCU + WiFi module)
- LoRa modules (SX1276) → long-range low-power wireless
- 433MHz ASK TX/RX pair → simplest possible wireless link
- AMS1117 → 3.3V regulator (replaces discrete regulator circuit)

### Topology Patterns for Common Functions

**Wireless link (simplest):**
- 433MHz ASK TX/RX modules + encoder/decoder ICs (HT12E/HT12D)
- No MCU needed, no programming, works out of the box
- Range: 20-100m depending on antenna
- Good for: single button → single action, garage door openers, remote switches

**Wireless link (flexible):**
- MCU + nRF24L01+ on both sides
- Requires programming but supports multiple channels, data packets, acknowledgment
- Range: 50-1000m with PA/LNA version
- Good for: multi-button remotes, sensor data, bidirectional communication

**Wireless link (internet-connected):**
- ESP32 on both sides (or one side + cloud server)
- WiFi, Bluetooth, or ESP-NOW protocol
- Requires programming and WiFi infrastructure
- Good for: IoT devices, phone-controlled gadgets, data logging

**Simple on/off control:**
- Comparator + reference voltage → transistor switch
- No MCU, no programming, purely analog
- Good for: thermostat, light-level switch, voltage monitor

**Analog signal processing:**
- Op-amp gain stages, active filters, mixers
- For audio, radio, sensor signal conditioning
- Calculations required: gain, bandwidth, filter cutoff, impedance matching

### Making the Choice

For each block in your diagram, write down:
1. The chosen approach (module name or discrete topology)
2. Why this approach (cost, simplicity, performance, availability)
3. Key specs that constrain downstream component selection

---

## Phase 3: Circuit Design & Calculations

Now design the actual circuits. For each block, produce a schematic-level design
with calculated component values.

### General Approach

1. **Start with the datasheet application circuit** — most ICs and modules have
   a "typical application" schematic. Use it as your starting point. Don't reinvent
   what the IC manufacturer already optimized.

2. **Calculate required values** — gain, bias points, filter frequencies, timing
   constants. Show your work so the user can verify and adjust.

3. **Add protection and robustness** — input protection (ESD, reverse polarity),
   decoupling caps on every IC power pin, pull-up/down resistors on unused inputs.

4. **Check power budget** — add up the current draw of every block. Make sure
   your power supply can handle it with margin (aim for 50% headroom in prototypes).

### Calculation Reference

**Voltage divider:**
  Vout = Vin × (R2 / (R1 + R2))

**RC time constant (debounce, timing):**
  τ = R × C
  For debounce: τ ≈ 5-20ms → R=10kΩ, C=1µF gives τ=10ms

**Op-amp gain (non-inverting):**
  Gain = 1 + (Rf / Rg)

**Op-amp gain (inverting):**
  Gain = -(Rf / Rin)

**Low-pass filter cutoff:**
  fc = 1 / (2π × R × C)

**LED current limiting:**
  R = (Vsupply - Vled) / Iled
  Typical: Vled≈2V (red), Iled≈10-20mA

**Transistor switch (NPN, driving a load):**
  Rbase = (Vcontrol - 0.7V) / (Iload / hFE × 10)
  The ×10 ensures saturation. hFE from datasheet (use minimum value).

**555 timer (astable):**
  f = 1.44 / ((R1 + 2×R2) × C)

**LC resonance:**
  f = 1 / (2π × √(L × C))

**Power dissipation (linear regulator):**
  P = (Vin - Vout) × Iload
  If P > 1W, consider a switching regulator instead.

### Design Output Format

For each circuit block, produce:

```
## [Block Name]

### Function
[One sentence: what this block does]

### Schematic
[ASCII schematic or description of connections]

### Component Values
| Ref | Value | Calculation / Rationale |
|-----|-------|------------------------|
| R1  | 10kΩ  | Pull-up, datasheet recommended |
| C1  | 100nF | Bypass cap, standard for this IC |

### Critical Notes
- [Anything the layout or assembly person needs to know]
- [Thermal considerations, sensitive nodes, matching requirements]
```

---

## Phase 4: Component Selection

Select specific, purchasable components for every value in the circuit.

### Selection Order (Same as easyeda-design-assistant Phase 2)

1. **ICs and modules first** — these constrain everything else
2. **Passives matched to IC requirements** — values from datasheets and calculations
3. **Connectors, switches, mechanical parts** — driven by enclosure and user interface
4. **Protection components** — ESD, fuses, TVS diodes

### The Parts Map

Produce the shared parts map that downstream skills consume:

```
| Ref | Value | MFR Part | DigiKey PN | LCSC | Package | Notes |
|-----|-------|----------|------------|------|---------|-------|
| U1  | nRF24L01+ | ... | ... | ... | Module | 2.4GHz transceiver |
```

**Critical: include LCSC part numbers.** Even if buying from DigiKey for a prototype,
the LCSC number is what makes EasyEDA footprint linking work. If you can't find an
exact LCSC match, find a sibling part with the same footprint.

### Availability Check

Before finalizing the parts map, verify:
- **In stock** at the intended supplier (DigiKey, LCSC, Mouser)
- **Not EOL** (end-of-life) — check manufacturer status
- **LCSC Basic vs Extended** — Basic parts are cheaper for JLCPCB assembly
- **Lead time** — if it's 16 weeks, find an alternative now

If a part fails availability checks, **loop back** to Phase 3 and adjust the design.
This is the V-model in action — don't force an unavailable part into a design.

### Generate the Netlist JSON

After the parts map is finalized and availability is confirmed, produce a structured
netlist JSON file. This is the machine-readable output that the **generate-schematic**
skill's Python engine (`scripts/generate_easyeda_schematic.py`) consumes to auto-generate
an importable EasyEDA schematic.

#### Netlist JSON Schema

```json
{
  "title": "Project Name",
  "description": "Brief project description",
  "components": {
    "R1": { "lcsc": "C723553",  "value": "1kΩ" },
    "R2": { "lcsc": "C119208",  "value": "20kΩ" },
    "C1": { "lcsc": "C1620078", "value": "100nF" },
    "U1": { "lcsc": "C7236",    "value": "TL072CP" }
  },
  "nets": {
    "VCC":   ["R1.1", "R2.1", "U1.8"],
    "GND":   ["C1.2", "U1.4"],
    "SIG_A": ["R1.2", "C1.1"],
    "FB":    ["R2.2", "U1.1", "U1.2"]
  }
}
```

#### How to Build the Netlist from Your Design

**Components object** — one entry per component on the parts map:
- Key = reference designator (R1, C1, U1, etc.)
- `lcsc` = the LCSC part number from the parts map (starts with C followed by digits)
- `value` = display value shown on the schematic (e.g., "1kΩ", "100nF", "TL072CP")

**Nets object** — one entry per electrical net in the circuit:
- Key = net name (descriptive: VCC, GND, HPF_OUT, BIAS_REF, etc.)
- Value = array of pin endpoints in `REF.PIN_NUMBER` format
- Every pin that participates in the circuit must appear in exactly one net

#### Finding Pin Numbers

Pin numbers must match the EasyEDA schematic symbol, not necessarily the physical
package. For common parts:
- **2-pin passives** (resistors, caps, diodes): pins are 1 and 2
- **3-pin transistors**: check the specific EasyEDA symbol (usually B=1, C=2, E=3
  but varies)
- **ICs**: pin numbers match the datasheet pin numbering (pin 1 = physical pin 1)
- **When in doubt**: look up the LCSC part on easyeda.com and open the schematic
  symbol to see pin numbers

#### Deriving Nets from the Circuit Design

Walk through each connection in the circuit schematics from Phase 3:

1. **Power rails** — collect every pin that connects to VCC, GND, +5V, -5V, etc.
   Don't forget IC power pins and decoupling cap connections.
2. **Signal paths** — trace each signal from source to destination. Every node
   where two or more component pins meet is a net.
3. **Feedback loops** — trace from output back to input. Each tap point is a net
   endpoint.
4. **Unused pins** — do NOT include unconnected pins. Only pins that are wired
   to something appear in the nets object.

#### Net Naming Conventions

Use descriptive names that make the schematic readable:
- Power: `VCC`, `GND`, `+5V`, `-5V`, `3V3`, `VBAT`
- Signals: `AUDIO_IN`, `FILTER_OUT`, `BIAS_REF`, `FB_NODE`
- Inter-block: `MCU_TX`, `MCU_RX`, `SPI_CLK`, `SPI_MOSI`
- Generic: `NET1`, `NET2` only as a last resort

#### Validation Checklist

Before handing off the netlist JSON:

- [ ] Every component in the parts map has an entry in `components`
- [ ] Every `lcsc` value starts with C followed by digits
- [ ] Every pin endpoint in `nets` references a valid designator from `components`
- [ ] No pin appears in more than one net
- [ ] All IC power pins are included in the appropriate power nets
- [ ] All bypass/decoupling caps are connected to the correct power and ground nets
- [ ] The net names are descriptive and consistent

#### Save Location

Save the netlist JSON alongside the design documentation:
```
{project_root}/scripts/netlist.json
```

This file feeds directly into the generate-schematic skill's pipeline:
```bash
python scripts/generate_easyeda_schematic.py \
    --netlist scripts/netlist.json \
    --output schematic.json
```

---

## Phase 5: Multi-Pass Design Verification

**This phase is not optional.** AI-generated circuit designs contain mistakes —
wrong passive values, missed protection, voltage mismatches, power sequencing
issues, missing pull-ups. A single review pass catches some errors but not all.

The reason this matters: a wrong resistor value in a simulation is a click to fix.
A wrong resistor value on a soldered PCB is hours of debugging, a new board spin,
and wasted parts. Catching it here costs nothing.

### Read `references/verification_checklist.md` for the full procedure.

The checklist has 4 passes that must be run iteratively:

1. **Power-On Walkthrough** — simulate applying power for the first time. Check
   reverse polarity, voltage spikes, regulator sequencing, inrush current, fault
   conditions (shorted outputs, disconnected inputs, dying battery).

2. **Component-by-Component Audit** — recalculate every resistor value from scratch,
   check every capacitor voltage rating (must be 2× max voltage), verify every IC pin
   against its datasheet (including unused pins), confirm transistor drive and flyback
   protection on inductive loads.

3. **Signal Integrity Walk** — trace every signal source to destination, check voltage
   levels and impedance compatibility, look for bus contention and missing filtering.

4. **Use-Case Scenario Walk** — mentally simulate the device in actual use against the
   original requirements. Normal operation, edge cases (hold button 30 seconds, press
   100 times rapidly, leave on overnight), environmental extremes, and user error
   (the dumbest thing someone could do — does it survive?).

### The 2-Clean-Pass Rule

Keep running verification passes until 2 consecutive passes find **zero issues**.
Any fix that changes component values or topology resets the counter — changes
cascade, and the whole point is to catch those cascades.

Document each pass with issues found, fixes applied, and severity. Only proceed
to Phase 6 (Handoff) after verification is complete.

---

## Phase 6: Handoff

Only reach this phase after Phase 5 verification is complete (2 clean passes).

### Output to User

The deliverables from this skill:

1. **Block diagram** with signal flow
2. **Circuit schematics** for each block with component values
3. **Parts map** with designators, values, manufacturer PNs, and LCSC numbers
4. **Netlist JSON** (`scripts/netlist.json`) — structured machine-readable netlist
   with components (ref + lcsc + value) and nets (name + REF.PIN endpoints),
   ready for the generate-schematic skill's Python engine
5. **Critical layout notes** (keep-close requirements, sensitive traces, thermal pads)
6. **Verification log** showing what was checked and any issues that were found and fixed

Tell the user: "The circuit design is complete and has been verified through [N]
review passes. The netlist JSON is ready at `scripts/netlist.json`. You can now
use the **generate-schematic** skill to auto-generate an importable EasyEDA
schematic from this netlist, or use the **easyeda-design-assistant** skill for
manual schematic entry and PCB preparation."

### Backtrack Triggers from Downstream

If the EasyEDA or manufacturing phase surfaces a problem, come back here:

- **"Part X has no LCSC footprint"** → find alternative part, update calculations if values change
- **"Board is too large"** → consider smaller packages, integrate functions, reduce component count
- **"Assembly cost too high"** → replace Extended parts with Basic, simplify circuit
- **"Performance doesn't meet spec after testing"** → adjust values, add filtering, change topology

Any design change from a backtrack trigger requires re-running Phase 5 verification
from scratch. A change in one place can cascade — the whole point of the multi-pass
approach is to catch those cascades.

---

## Common Circuit Templates

These are starting points, not complete designs. Always verify against your specific
requirements and adjust values accordingly.

### Template: Simple Wireless Button (433MHz ASK)

**TX Side:**
- Button → 10kΩ pull-up → HT12E encoder (pins A0-A7 set address, pin TE triggered by button)
- HT12E DOUT → 433MHz ASK TX module data pin
- Power: 3-12V battery, 100nF bypass on HT12E VDD
- Antenna: 17.3cm wire (quarter-wave for 433MHz)

**RX Side:**
- 433MHz ASK RX module data → HT12D decoder (same address as encoder)
- HT12D VT (valid transmission) → transistor switch → relay/LED/buzzer
- Power: 5V regulated, 100nF bypass on HT12D VDD
- Antenna: 17.3cm wire

**Key calculations:**
- HT12E oscillator: Rosc = 750kΩ (typical for 3V operation)
- HT12D oscillator: Rosc = 33kΩ (must be ~50× lower than encoder)
- Button debounce: 10kΩ + 100nF = 1ms time constant

### Template: MCU-Based Wireless (nRF24L01+)

**Both sides:**
- ATmega328P or STM32 MCU
- nRF24L01+ module connected via SPI (MOSI, MISO, SCK, CSN, CE)
- 10µF + 100nF decoupling on nRF24L01+ VCC (this module is power-sensitive)
- 3.3V regulator if MCU runs at 5V (nRF24L01+ is 3.3V only, pins are 5V tolerant)

**TX additions:**
- Button input with internal pull-up or external 10kΩ
- Status LED with 330Ω current-limiting resistor

**RX additions:**
- Output driver (NPN transistor + relay, or MOSFET for DC loads)
- Flyback diode across relay coil (1N4148)
- Status LED

### Template: Simple Audio Amplifier

- NE5532 or TL072 op-amp (DIP-8)
- Non-inverting configuration: Gain = 1 + (Rf/Rg)
- Input coupling cap: 1µF film or electrolytic
- Output coupling cap: 10µF electrolytic
- Bypass caps: 100nF on both supply rails, placed within 1cm of IC
- Dual supply: ±12V or ±15V

### Template: Sensor + Threshold Detector

- Sensor (thermistor, photoresistor, etc.) in voltage divider
- Op-amp comparator (LM393 or LM358) with reference voltage
- Hysteresis resistor to prevent oscillation at threshold
- Output to indicator LED or transistor switch
