#include "game_price/notification/notification.h"

#include <stdexcept>

namespace game_price {
std::string toString(AlertRuleType type) {
    switch (type) {
        case AlertRuleType::PriceDrop: return "PriceDrop";
        case AlertRuleType::BelowTargetPrice: return "BelowTargetPrice";
        case AlertRuleType::NewHistoricalLow: return "NewHistoricalLow";
        case AlertRuleType::BelowAverage: return "BelowAverage";
    }
    return "Unknown";
}
AlertRuleType alertRuleTypeFromString(const std::string& value) {
    if (value == "PriceDrop") return AlertRuleType::PriceDrop;
    if (value == "BelowTargetPrice") return AlertRuleType::BelowTargetPrice;
    if (value == "NewHistoricalLow") return AlertRuleType::NewHistoricalLow;
    if (value == "BelowAverage") return AlertRuleType::BelowAverage;
    throw std::invalid_argument("unsupported alert rule type");
}
}  // namespace game_price
