/*
 * Copyright (c) 2025 Nikhil Doal
 * SPDX-License-Identifier: Apache-2.0
 */

`default_nettype none

module spi_peripheral (
    input  wire       clk,           // System clock
    input  wire       rst_n,         // Active-low reset
    input  wire       nCS,           // SPI Chip Select (active low)
    input  wire       SCLK,          // SPI Clock
    input  wire       COPI,          // Controller Out Peripheral In
    output reg  [7:0] en_reg_out_7_0,    // Register 0x00
    output reg  [7:0] en_reg_out_15_8,   // Register 0x01
    output reg  [7:0] en_reg_pwm_7_0,    // Register 0x02
    output reg  [7:0] en_reg_pwm_15_8,   // Register 0x03
    output reg  [7:0] pwm_duty_cycle     // Register 0x04
);

    // Parameters
    localparam MAX_ADDRESS = 7'h04;
    
    // CDC Synchronizers (2-stage for value signals, 3-stage for edge detection)
    reg nCS_sync1, nCS_sync2;
    reg COPI_sync1, COPI_sync2;
    reg SCLK_sync1, SCLK_sync2, SCLK_sync3;
    
    // Edge detection
    wire nCS_negedge = (nCS_sync2 == 1'b0) && (nCS_sync1 == 1'b1);
    wire nCS_posedge = (nCS_sync2 == 1'b1) && (nCS_sync1 == 1'b0);
    wire SCLK_posedge = (SCLK_sync2 == 1'b1) && (SCLK_sync3 == 1'b0);
    
    // SPI state machine
    reg [15:0] shift_register;  // Holds incoming bits: [R/W bit][7-bit addr][8-bit data]
    reg [4:0] bit_counter;      // Counts bits received (0-15)
    reg transaction_active;
    
    // Transaction validation and handshaking
    reg transaction_ready;
    reg transaction_processed;
    wire is_write_operation = shift_register[15];
    wire [6:0] register_address = shift_register[14:8];
    wire [7:0] register_data = shift_register[7:0];
    wire is_valid_address = (register_address <= MAX_ADDRESS);
    wire is_transaction_valid = is_write_operation && is_valid_address;
    
    // Synchronizer chain
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            nCS_sync1 <= 1'b1;
            nCS_sync2 <= 1'b1;
            COPI_sync1 <= 1'b0;
            COPI_sync2 <= 1'b0;
            SCLK_sync1 <= 1'b0;
            SCLK_sync2 <= 1'b0;
            SCLK_sync3 <= 1'b0;
        end else begin
            // Synchronize nCS
            nCS_sync1 <= nCS;
            nCS_sync2 <= nCS_sync1;
            
            // Synchronize COPI
            COPI_sync1 <= COPI;
            COPI_sync2 <= COPI_sync1;
            
            // Synchronize SCLK (needs 3 stages for edge detection)
            SCLK_sync1 <= SCLK;
            SCLK_sync2 <= SCLK_sync1;
            SCLK_sync3 <= SCLK_sync2;
        end
    end
    
    // SPI protocol processing
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            shift_register <= 16'h0000;
            bit_counter <= 5'd0;
            transaction_active <= 1'b0;
            transaction_ready <= 1'b0;
        end else if (nCS_sync2 == 1'b0) begin
            // Transaction is active when CS is low
            transaction_active <= 1'b1;
            
            // Sample data on SCLK rising edge (Mode 0)
            if (SCLK_posedge) begin
                // Shift in the bit
                shift_register <= {shift_register[14:0], COPI_sync2};
                bit_counter <= bit_counter + 1'b1;
            end
        end else begin
            // When nCS goes high (transaction ends)
            if (nCS_posedge && transaction_active) begin
                // Check if we received exactly 16 bits
                if (bit_counter == 5'd16) begin
                    transaction_ready <= 1'b1;
                end
                transaction_active <= 1'b0;
                bit_counter <= 5'd0;
            end else if (transaction_processed) begin
                // Clear ready flag once processed
                transaction_ready <= 1'b0;
            end
        end
    end
    
    // Register update logic
    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            en_reg_out_7_0 <= 8'h00;
            en_reg_out_15_8 <= 8'h00;
            en_reg_pwm_7_0 <= 8'h00;
            en_reg_pwm_15_8 <= 8'h00;
            pwm_duty_cycle <= 8'h00;
            transaction_processed <= 1'b0;
        end else if (transaction_ready && !transaction_processed) begin
            // Transaction is ready and not yet processed
            if (is_transaction_valid) begin
                // Update the appropriate register based on address
                case (register_address)
                    7'h00: en_reg_out_7_0 <= register_data;
                    7'h01: en_reg_out_15_8 <= register_data;
                    7'h02: en_reg_pwm_7_0 <= register_data;
                    7'h03: en_reg_pwm_15_8 <= register_data;
                    7'h04: pwm_duty_cycle <= register_data;
                    default: ; // Invalid address, do nothing
                endcase
            end
            // Set the processed flag
            transaction_processed <= 1'b1;
        end else if (!transaction_ready && transaction_processed) begin
            // Reset processed flag when ready flag is cleared
            transaction_processed <= 1'b0;
        end
    end

endmodule