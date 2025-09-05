`default_nettype none

module spi_peripheral (
    input  wire       clk,      // clock
    input  wire       rst_n,    // active low asynch reset

    input wire sclk,
    input wire copi,    
    input wire ncs,

    output reg [7:0] en_reg_out_7_0,
    output reg [7:0] en_reg_out_15_8,
    output reg [7:0] en_reg_pwm_7_0,
    output reg [7:0] en_reg_pwm_15_8,
    output reg [7:0] pwm_duty_cycle
);

    reg [15:0] received_message; // [15] = r/w, [14:8] = register to write to, [7:0] = data bits
    reg [4:0]  bit_count; // count up to 16 SCLK edges to know when transaction is complete

    reg [2:0] sclk_synch;
    reg [2:0] ncs_synch;
    reg [1:0] copi_synch;

    wire transaction_ready = (bit_count == 5'd16) ? 1 : 0;
    wire posedge_sclk      = ~sclk_synch[2] && sclk_synch[1];
    wire posedge_ncs       = ~ncs_synch[2] && ncs_synch[1];
    wire negedge_ncs       = ncs_synch[2] && ~ncs_synch[1];
    wire low_ncs           = ~ncs_synch[2] && ~ncs_synch[1];

    always @(posedge clk or negedge rst_n) begin
        if (!rst_n) begin
            received_message <= '0;
            bit_count <= '0;
            ncs_synch <= '0;
            copi_synch <= '0;
            sclk_synch <= '0;
            en_reg_out_7_0 <= '0;
            en_reg_out_15_8 <= '0;
            en_reg_pwm_7_0 <= '0;
            en_reg_pwm_15_8 <= '0;
            pwm_duty_cycle <= '0;
        end

        else begin
            // synchronizer FF chain to avoid metastability
            // oldest = [2] -> [1] -> [0] = newest
            ncs_synch <= {ncs_synch[1:0], ncs};
            sclk_synch <= {sclk_synch[1:0], sclk};

            // oldest = [1] -> [0] = newest
            copi_synch <= {copi_synch[0], copi};
            
            // reset message and bit count on falling edge of nCS to start transaction
            if (negedge_ncs) begin
                received_message <= '0;
                bit_count <= '0;
            end

            // nCS pulled low during transaction, shift in data on rising SCLK edge (SPI Mode 0)
            else if (low_ncs && posedge_sclk && !transaction_ready) begin
                received_message <= {received_message[14:0], copi_synch[1]};
                bit_count <= bit_count + 1;
            end

            // transaction complete on rising edge of nCS
            else if (posedge_ncs) begin
                if (transaction_ready && received_message[15]) begin
                    case (received_message[14:8])
                        7'h00   : en_reg_out_7_0 <= received_message[7:0];
                        7'h01   : en_reg_out_15_8 <= received_message[7:0];
                        7'h02   : en_reg_pwm_7_0 <= received_message[7:0];
                        7'h03   : en_reg_pwm_15_8 <= received_message[7:0];
                        7'h04   : pwm_duty_cycle <= received_message[7:0];
                        default :; // do nothing for invalid addresses
                    endcase
                end
            end
        end
    end
endmodule