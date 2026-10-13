package example.domain;

public class BulkPricing implements PricingPolicy {

    @Override
    public int total(int unitCents, int quantity) {
        if (unitCents < 0 || quantity <= 0) {
            throw new IllegalArgumentException("unitCents must be >=0 and quantity >0");
        }
        long raw = (long) unitCents * quantity;
        if (quantity >= 2) {
            return (int) Math.round(raw * 0.9);
        }
        return (int) raw;
    }
}
