# Circuit Design Verification Checklist

Detailed verification passes for Phase 5 of the circuit-designer skill.
Read this file when performing design verification. Run all 4 passes
iteratively until 2 consecutive passes find zero issues.

## How Verification Works

1. Complete a verification pass (all checks below)
2. Fix every issue found
3. Do another verification pass on the corrected design
4. Repeat until a pass finds **zero issues**
5. Then do **one more clean pass** to confirm (2 consecutive clean passes required)

If a fix in one area introduces a change elsewhere (e.g., swapping a part changes
the required bias resistor), the count resets — you need 2 clean passes from that point.

---

## Pass 1: Power-On Walkthrough

Imagine you've built this circuit and are about to apply power for the first time.
Walk through it physically:

### Before power is applied:
- Are there any paths where current can flow before the regulators stabilize?
- If battery is inserted backwards, what happens? Is there reverse polarity protection?
- If the power switch is on when you plug in the battery, does anything see a voltage
  spike above its absolute maximum rating?

### The moment power is applied (t=0):
- What voltage does each IC see at its power pins? Trace the path from supply to each IC.
- Do all regulators have their input and output caps? (check each one individually)
- If there are multiple voltage rails, what's the power-up sequence? Do any ICs
  require rail A before rail B?
- What's the inrush current? Can the supply handle it?

### Steady state:
- For every IC, check: is Vcc within the datasheet's recommended operating range?
- For every signal between blocks: is the voltage level compatible? (3.3V output
  into a 5V input is usually fine; 5V output into a 3.3V input may destroy it)
- What's the total current draw? Does it match the power budget with margin?

### Fault conditions:
- If the output is shorted, does anything burn? (add current limiting if needed)
- If an input is disconnected (antenna removed, sensor unplugged), does the circuit
  behave gracefully or does it oscillate/latch up?
- If the battery dies slowly (voltage drops from 4.5V to 2.5V), at what point does
  the circuit malfunction? Is that failure safe?

---

## Pass 2: Component-by-Component Audit

Go through every single component in the parts map and verify:

### For every resistor:
- Recalculate the value from scratch. Does the formula give this number?
- Check power dissipation: P = V²/R or P = I²×R. Is the wattage rating adequate?
  (A 1/4W resistor with 0.5W across it will burn)
- For pull-ups/pull-downs: is the value appropriate for the signal speed and
  current capability of the driving pin?

### For every capacitor:
- Is the voltage rating at least 2× the maximum voltage it will see?
  (A 6.3V cap on a 5V rail is marginal — use 10V or 16V)
- For decoupling caps: is there one within 1cm of every IC power pin?
- For coupling caps: does the value give adequate low-frequency response?
  fc = 1/(2π×R×C) — if R is the load impedance, is fc below your signal band?
- Electrolytic caps: is the polarity correct in the schematic?

### For every IC:
- Check every pin against the datasheet. Not just the pins you're using — also
  the ones you're NOT using. Floating inputs cause erratic behavior.
- Are unused op-amp inputs tied to a valid voltage?
- Are unused digital inputs pulled to Vcc or GND?
- Check the absolute maximum ratings. Does any pin ever see a voltage outside
  the abs max range, even transiently?
- Check the recommended operating conditions (not just abs max). Is the IC
  operating in its happy zone?

### For every transistor/MOSFET:
- Base/gate drive: is the drive signal strong enough to fully turn on the device?
  For NPN: verify Ib > Ic/hFE(min) with safety margin
  For MOSFET: verify Vgs > Vgs(th) by at least 2V for full enhancement
- Is there a flyback/freewheeling diode on inductive loads (relays, motors, solenoids)?
- Check power dissipation: Pd = Vce(sat) × Ic for BJT, Pd = Rds(on) × Id² for MOSFET
- Is the device's Vce or Vds rating adequate for the circuit voltage?

### For every connector:
- Can the user plug it in wrong? (reversed polarity, wrong connector type)
- Is there protection against ESD on exposed connectors?
- For RF connectors: is the impedance matched (50Ω for most RF)?

---

## Pass 3: Signal Integrity Walk

Trace every signal path from source to destination:

- Does the signal arrive at the right voltage level?
- Is the source impedance compatible with the load impedance?
  (High-Z source into low-Z load = signal loss; guitar pickup into 1kΩ = bad)
- Are there any points where two outputs drive the same net? (bus contention)
- For analog signals: is there adequate filtering to prevent noise/interference?
- For digital signals: are there proper termination resistors on long traces?
- For RF signals: is impedance matching correct throughout the chain?

---

## Pass 4: Use-Case Scenario Walk

Go back to the user's original requirements and mentally simulate the device in use:

- **Normal operation:** User presses the button / reads the display / plugs in audio.
  Does the circuit do exactly what was asked? Not almost, not close — exactly.
- **Edge cases:** What if the user holds the button for 30 seconds? What if they
  press it 100 times rapidly? What if they leave it on overnight?
- **Environmental:** What happens at the temperature extremes of the intended
  environment? In bright sunlight? In the rain? (if outdoor)
- **User error:** What's the dumbest thing a user could do? Plug headphones into
  the mic jack? Connect 12V to a 5V input? Leave it in the car in summer?
  Design should survive (or at least not catch fire).

---

## Verification Output Format

After each pass, document findings:

```
## Verification Pass [N]

### Issues Found: [count]

1. **[CRITICAL/WARNING/NOTE]** [Component Ref] — [Description]
   - Problem: [What's wrong]
   - Fix: [What to change]
   - Impact: [What would happen if not fixed]

### Status: [CLEAN / issues found — fix and re-verify]
```

After 2 consecutive clean passes:

```
## Verification Complete
- Total passes: [N]
- Issues found and fixed: [count]
- Design status: VERIFIED — ready for handoff
```
