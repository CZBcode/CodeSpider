package example.domain;

public interface PricingPolicy {
    int total(int unitCents, int quantity);
}
