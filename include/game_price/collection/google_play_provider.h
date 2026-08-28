#pragma once

#include "game_price/collection/store_product_provider.h"

#include <cstdint>
#include <string>
#include <vector>

namespace game_price {

class GooglePlayProvider final : public StoreProductProvider {
public:
    explicit GooglePlayProvider(const std::string& dataPath);
    Store store() const noexcept override;
    std::vector<StoreProduct> findProducts(const std::string& gameId) const override;
    std::vector<ProviderRejection> findRejections(
        const std::string& gameId) const override;

private:
    struct RawProduct {
        std::string packageName;
        std::string gameId;
        std::int64_t priceMicros{};
        bool published{false};
    };

    std::vector<RawProduct> products_;
    std::vector<ProviderRejection> rejections_;
};

}  // namespace game_price
