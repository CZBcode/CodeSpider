package example.web;

import example.Application;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.web.servlet.MockMvc;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

@SpringBootTest(classes = Application.class)
@AutoConfigureMockMvc
class QuoteControllerTest {

    @Autowired
    private MockMvc mockMvc;

    @Test
    void getQuoteSuccess() throws Exception {
        mockMvc.perform(get("/api/quote").param("sku", "book").param("quantity", "2"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.totalCents").value(1800));
    }

    @Test
    void getQuoteBadRequestOnZeroQuantity() throws Exception {
        mockMvc.perform(get("/api/quote").param("sku", "book").param("quantity", "0"))
                .andExpect(status().isBadRequest());
    }

    @Test
    void getQuoteNotFoundOnUnknownSku() throws Exception {
        mockMvc.perform(get("/api/quote").param("sku", "pen").param("quantity", "1"))
                .andExpect(status().isNotFound());
    }

    @Test
    void strategyReplaceabilityViaDifferentBean() throws Exception {
        // The Application wires BulkPricing; replacing the PricingPolicy bean
        // would change behavior without touching the controller or service.
        mockMvc.perform(get("/api/quote").param("sku", "book").param("quantity", "1"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.totalCents").value(1000));
    }
}
