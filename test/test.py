# SPDX-FileCopyrightText: © 2024 Tiny Tapeout
# SPDX-License-Identifier: Apache-2.0

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import RisingEdge, FallingEdge
from cocotb.triggers import ClockCycles
from cocotb.types import Logic
from cocotb.types import LogicArray

async def await_half_sclk(dut):
    """Wait for the SCLK signal to go high or low."""
    start_time = cocotb.utils.get_sim_time(units="ns")
    while True:
        await ClockCycles(dut.clk, 1)
        # Wait for half of the SCLK period (10 us)
        if (start_time + 100*100*0.5) < cocotb.utils.get_sim_time(units="ns"):
            break
    return

def ui_in_logicarray(ncs, bit, sclk):
    """Setup the ui_in value as a LogicArray."""
    return LogicArray(f"00000{ncs}{bit}{sclk}")

async def send_spi_transaction(dut, r_w, address, data):
    """
    Send an SPI transaction with format:
    - 1 bit for Read/Write
    - 7 bits for address
    - 8 bits for data
    
    Parameters:
    - r_w: boolean, True for write, False for read
    - address: int, 7-bit address (0-127)
    - data: LogicArray or int, 8-bit data
    """
    # Convert data to int if it's a LogicArray
    if isinstance(data, LogicArray):
        data_int = int(data)
    else:
        data_int = data
    # Validate inputs
    if address < 0 or address > 127:
        raise ValueError("Address must be 7-bit (0-127)")
    if data_int < 0 or data_int > 255:
        raise ValueError("Data must be 8-bit (0-255)")
    # Combine RW and address into first byte
    first_byte = (int(r_w) << 7) | address
    # Start transaction - pull CS low
    sclk = 0
    ncs = 0
    bit = 0
    # Set initial state with CS low
    dut.ui_in.value = ui_in_logicarray(ncs, bit, sclk)
    await ClockCycles(dut.clk, 1)
    # Send first byte (RW + Address)
    for i in range(8):
        bit = (first_byte >> (7-i)) & 0x1
        # SCLK low, set COPI
        sclk = 0
        dut.ui_in.value = ui_in_logicarray(ncs, bit, sclk)
        await await_half_sclk(dut)
        # SCLK high, keep COPI
        sclk = 1
        dut.ui_in.value = ui_in_logicarray(ncs, bit, sclk)
        await await_half_sclk(dut)
    # Send second byte (Data)
    for i in range(8):
        bit = (data_int >> (7-i)) & 0x1
        # SCLK low, set COPI
        sclk = 0
        dut.ui_in.value = ui_in_logicarray(ncs, bit, sclk)
        await await_half_sclk(dut)
        # SCLK high, keep COPI
        sclk = 1
        dut.ui_in.value = ui_in_logicarray(ncs, bit, sclk)
        await await_half_sclk(dut)
    # End transaction - return CS high
    sclk = 0
    ncs = 1
    bit = 0
    dut.ui_in.value = ui_in_logicarray(ncs, bit, sclk)
    await ClockCycles(dut.clk, 600)
    return ui_in_logicarray(ncs, bit, sclk)

async def wait_for_edge(dut, signal, edge_type='rising', timeout_ns=1000000):
    """
    Wait for a rising or falling edge on a signal.
    Returns the time of the edge in nanoseconds, or None if timeout.
    """
    start_time = cocotb.utils.get_sim_time(units="ns")
    
    if edge_type == 'rising':
        prev_value = int(signal.value)
        while True:
            await ClockCycles(dut.clk, 1)
            curr_value = int(signal.value)
            if prev_value == 0 and curr_value == 1:
                return cocotb.utils.get_sim_time(units="ns")
            prev_value = curr_value
            
            if cocotb.utils.get_sim_time(units="ns") - start_time > timeout_ns:
                return None
    else:  # falling
        prev_value = int(signal.value)
        while True:
            await ClockCycles(dut.clk, 1)
            curr_value = int(signal.value)
            if prev_value == 1 and curr_value == 0:
                return cocotb.utils.get_sim_time(units="ns")
            prev_value = curr_value
            
            if cocotb.utils.get_sim_time(units="ns") - start_time > timeout_ns:
                return None

async def measure_pwm_period_and_duty(dut, signal, num_periods=3):
    """
    Measure PWM frequency and duty cycle.
    Returns (avg_period_ns, avg_duty_cycle_percent)
    """
    periods = []
    duty_cycles = []
    
    for _ in range(num_periods):
        # Wait for rising edge
        t1 = await wait_for_edge(dut, signal, 'rising', timeout_ns=2000000)
        if t1 is None:
            # Signal might be stuck low (0% duty cycle)
            return None, 0.0
        
        # Wait for falling edge
        t2 = await wait_for_edge(dut, signal, 'falling', timeout_ns=2000000)
        if t2 is None:
            # Signal might be stuck high (100% duty cycle)
            return None, 100.0
        
        # Wait for next rising edge
        t3 = await wait_for_edge(dut, signal, 'rising', timeout_ns=2000000)
        if t3 is None:
            # Could be last period or stuck low
            break
        
        period = t3 - t1
        high_time = t2 - t1
        
        if period > 0:
            periods.append(period)
            duty_cycles.append((high_time / period) * 100.0)
    
    if len(periods) == 0:
        return None, None
    
    avg_period = sum(periods) / len(periods)
    avg_duty = sum(duty_cycles) / len(duty_cycles)
    
    return avg_period, avg_duty

@cocotb.test()
async def test_spi(dut):
    dut._log.info("Start SPI test")

    # Set the clock period to 100 ns (10 MHz)
    clock = Clock(dut.clk, 100, units="ns")
    cocotb.start_soon(clock.start())

    # Reset
    dut._log.info("Reset")
    dut.ena.value = 1
    ncs = 1
    bit = 0
    sclk = 0
    dut.ui_in.value = ui_in_logicarray(ncs, bit, sclk)
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 5)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 5)

    dut._log.info("Test project behavior")
    dut._log.info("Write transaction, address 0x00, data 0xF0")
    ui_in_val = await send_spi_transaction(dut, 1, 0x00, 0xF0)  # Write transaction
    assert dut.uo_out.value == 0xF0, f"Expected 0xF0, got {dut.uo_out.value}"
    await ClockCycles(dut.clk, 1000) 

    dut._log.info("Write transaction, address 0x01, data 0xCC")
    ui_in_val = await send_spi_transaction(dut, 1, 0x01, 0xCC)  # Write transaction
    assert dut.uio_out.value == 0xCC, f"Expected 0xCC, got {dut.uio_out.value}"
    await ClockCycles(dut.clk, 100)

    dut._log.info("Write transaction, address 0x30 (invalid), data 0xAA")
    ui_in_val = await send_spi_transaction(dut, 1, 0x30, 0xAA)
    await ClockCycles(dut.clk, 100)

    dut._log.info("Read transaction (invalid), address 0x00, data 0xBE")
    ui_in_val = await send_spi_transaction(dut, 0, 0x30, 0xBE)
    assert dut.uo_out.value == 0xF0, f"Expected 0xF0, got {dut.uo_out.value}"
    await ClockCycles(dut.clk, 100)
    
    dut._log.info("Read transaction (invalid), address 0x41 (invalid), data 0xEF")
    ui_in_val = await send_spi_transaction(dut, 0, 0x41, 0xEF)
    await ClockCycles(dut.clk, 100)

    dut._log.info("Write transaction, address 0x02, data 0xFF")
    ui_in_val = await send_spi_transaction(dut, 1, 0x02, 0xFF)  # Write transaction
    await ClockCycles(dut.clk, 100)

    dut._log.info("Write transaction, address 0x04, data 0xCF")
    ui_in_val = await send_spi_transaction(dut, 1, 0x04, 0xCF)  # Write transaction
    await ClockCycles(dut.clk, 30000)

    dut._log.info("Write transaction, address 0x04, data 0xFF")
    ui_in_val = await send_spi_transaction(dut, 1, 0x04, 0xFF)  # Write transaction
    await ClockCycles(dut.clk, 30000)

    dut._log.info("Write transaction, address 0x04, data 0x00")
    ui_in_val = await send_spi_transaction(dut, 1, 0x04, 0x00)  # Write transaction
    await ClockCycles(dut.clk, 30000)

    dut._log.info("Write transaction, address 0x04, data 0x01")
    ui_in_val = await send_spi_transaction(dut, 1, 0x04, 0x01)  # Write transaction
    await ClockCycles(dut.clk, 30000)

    dut._log.info("SPI test completed successfully")

@cocotb.test()
async def test_pwm_freq(dut):
    """Test that PWM frequency is 3 kHz (±1% tolerance)."""
    dut._log.info("Start PWM Frequency test")
    
    # Set the clock period to 100 ns (10 MHz)
    clock = Clock(dut.clk, 100, units="ns")
    cocotb.start_soon(clock.start())

    # Reset
    dut._log.info("Reset")
    dut.ena.value = 1
    ncs = 1
    bit = 0
    sclk = 0
    dut.ui_in.value = ui_in_logicarray(ncs, bit, sclk)
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 10)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 10)

    # Configure PWM:
    # 1. Enable output on uo_out[0] (register 0x00)
    dut._log.info("Enable output on uo_out[0]")
    await send_spi_transaction(dut, 1, 0x00, 0x01)
    await ClockCycles(dut.clk, 100)
    
    # 2. Enable PWM mode on uo_out[0] (register 0x02)
    dut._log.info("Enable PWM mode on uo_out[0]")
    await send_spi_transaction(dut, 1, 0x02, 0x01)
    await ClockCycles(dut.clk, 100)
    
    # 3. Set duty cycle to 50% (register 0x04 = 0x80)
    dut._log.info("Set duty cycle to 50% (0x80)")
    await send_spi_transaction(dut, 1, 0x04, 0x80)
    await ClockCycles(dut.clk, 1000)
    
    # Measure PWM period and frequency
    dut._log.info("Measuring PWM frequency...")
    period_ns, duty = await measure_pwm_period_and_duty(dut, dut.uo_out[0], num_periods=5)
    
    if period_ns is None:
        raise AssertionError("Could not measure PWM period - signal may be stuck")
    
    # Calculate frequency
    frequency_hz = 1_000_000_000 / period_ns  # Convert ns to Hz
    dut._log.info(f"Measured frequency: {frequency_hz:.2f} Hz")
    dut._log.info(f"Measured period: {period_ns:.2f} ns")
    
    # Expected: 3000 Hz ± 1%
    expected_freq = 3000
    tolerance = 0.01
    min_freq = expected_freq * (1 - tolerance)
    max_freq = expected_freq * (1 + tolerance)
    
    assert min_freq <= frequency_hz <= max_freq, \
        f"Frequency {frequency_hz:.2f} Hz out of range [{min_freq:.2f}, {max_freq:.2f}] Hz"
    
    dut._log.info(f"PWM Frequency test passed! Frequency: {frequency_hz:.2f} Hz (expected {expected_freq} Hz ±1%)")

@cocotb.test()
async def test_pwm_duty(dut):
    """Test PWM duty cycle accuracy (±1% tolerance)."""
    dut._log.info("Start PWM Duty Cycle test")
    
    # Set the clock period to 100 ns (10 MHz)
    clock = Clock(dut.clk, 100, units="ns")
    cocotb.start_soon(clock.start())

    # Reset
    dut._log.info("Reset")
    dut.ena.value = 1
    ncs = 1
    bit = 0
    sclk = 0
    dut.ui_in.value = ui_in_logicarray(ncs, bit, sclk)
    dut.uio_in.value = 0
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 10)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 10)

    # Enable output and PWM mode on uo_out[0]
    await send_spi_transaction(dut, 1, 0x00, 0x01)  # Enable output
    await ClockCycles(dut.clk, 100)
    await send_spi_transaction(dut, 1, 0x02, 0x01)  # Enable PWM
    await ClockCycles(dut.clk, 100)

    # Test different duty cycles
    test_cases = [
        (0x00, 0.0, "0%"),      # 0% duty cycle
        (0x40, 25.0, "25%"),    # 25% duty cycle (64/256)
        (0x80, 50.0, "50%"),    # 50% duty cycle (128/256)
        (0xC0, 75.0, "75%"),    # 75% duty cycle (192/256)
        (0xFF, 100.0, "100%"),  # 100% duty cycle
    ]
    
    tolerance = 1.0  # ±1%
    
    for duty_value, expected_duty, description in test_cases:
        dut._log.info(f"Testing {description} duty cycle (register value: 0x{duty_value:02X})")
        
        # Set duty cycle
        await send_spi_transaction(dut, 1, 0x04, duty_value)
        await ClockCycles(dut.clk, 2000)
        
        # Measure duty cycle
        if expected_duty == 0.0:
            # Special case: 0% - signal should stay low
            await ClockCycles(dut.clk, 50000)  # Wait a bit
            # Check that signal never goes high
            signal_value = int(dut.uo_out[0].value)
            assert signal_value == 0, f"Expected signal to be 0 for 0% duty, got {signal_value}"
            dut._log.info(f"✓ {description} duty cycle: Signal correctly stays LOW")
            
        elif expected_duty == 100.0:
            # Special case: 100% - signal should stay high
            await ClockCycles(dut.clk, 50000)  # Wait a bit
            # Check that signal never goes low
            signal_value = int(dut.uo_out[0].value)
            assert signal_value == 1, f"Expected signal to be 1 for 100% duty, got {signal_value}"
            dut._log.info(f"✓ {description} duty cycle: Signal correctly stays HIGH")
            
        else:
            # Normal case: measure duty cycle
            period_ns, measured_duty = await measure_pwm_period_and_duty(dut, dut.uo_out[0], num_periods=5)
            
            if measured_duty is None:
                raise AssertionError(f"Could not measure duty cycle for {description}")
            
            dut._log.info(f"Measured duty cycle: {measured_duty:.2f}%")
            
            # Check tolerance
            min_duty = expected_duty - tolerance
            max_duty = expected_duty + tolerance
            
            assert min_duty <= measured_duty <= max_duty, \
                f"Duty cycle {measured_duty:.2f}% out of range [{min_duty:.2f}%, {max_duty:.2f}%]"
            
            dut._log.info(f"✓ {description} duty cycle passed! Measured: {measured_duty:.2f}% (expected {expected_duty}% ±1%)")
    
    dut._log.info("PWM Duty Cycle test completed successfully!")