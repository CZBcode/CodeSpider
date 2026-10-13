package example.service;

import example.domain.PricingPolicy;
import example.repository.ProductRepository;
import org.junit.jupiter.api.Test;

import java.util.NoSuchElementException;

import static org.junit.jupiter.api.Assertions.*;

class QuoteServiceTest {

    private final ProductRepository repo = sku -> {
        if ("book".equals(sku)) return 1000;
        throw new NoSuchElementException("Unknown SKU: " + sku);
    };

    private final PricingPolicy policy = (unit, qty) -> {
        if (unit < 0 || qty <= 0) throw new IllegalArgumentException();
        long raw = (long) unit * qty;
        return qty >= 2 ? (int) Math.round(raw * 0.9) : (int) raw;
    };

    private final QuoteService service = new QuoteService(repo, policy);

    @Test
    void quoteSingleItem() {
        assertEquals(1000, service.quote("book", 1));
    }

    @Test
    void quoteBulkDiscount() {
        assertEquals(1800, service.quote("book", 2));
    }

    @Test
    void quoteInvalidQuantityThrows() {
        assertThrows(IllegalArgumentException.class, () -> service.quote("book", 0));
    }

    @Test
    void quoteUnknownSkuThrows() {
        assertThrows(NoSuchElementException.class, () -> service.quote("pen", 1));
    }

    @Test
    void strategyIsReplaceable() {
        PricingPolicy fixedPolicy = (u, q) -> u * q;
        QuoteService fixedService = new QuoteService(repo, fixedPolicy);
        assertEquals(2000, fixedService.quote("book", 2));
    }
}
