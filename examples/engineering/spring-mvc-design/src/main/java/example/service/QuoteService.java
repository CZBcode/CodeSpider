package example.service;

import example.domain.PricingPolicy;
import example.repository.ProductRepository;

public class QuoteService {

    private final ProductRepository repository;
    private final PricingPolicy pricing;

    public QuoteService(ProductRepository repository, PricingPolicy pricing) {
        this.repository = repository;
        this.pricing = pricing;
    }

    public int quote(String sku, int quantity) {
        if (quantity <= 0) {
            throw new IllegalArgumentException("quantity must be > 0");
        }
        int unitCents = repository.unitPrice(sku);
        return pricing.total(unitCents, quantity);
    }
}
