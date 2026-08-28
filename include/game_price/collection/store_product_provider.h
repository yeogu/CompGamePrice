#pragma once

#include "game_price/domain/store_product.h"

#include <string>
#include <vector>

namespace game_price {

struct ProviderRejection {
    std::string gameId;
    std::string productId;
    std::string reason;
};

class StoreProductProvider {
public:
    virtual ~StoreProductProvider() = default;
    virtual Store store() const noexcept = 0;
    virtual std::vector<StoreProduct> findProducts(const std::string& gameId) const = 0;
    virtual std::vector<ProviderRejection> findRejections(
        const std::string&) const {
        return {};
    }
};

}  // namespace game_price
