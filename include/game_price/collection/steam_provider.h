#pragma once

#include "game_price/collection/store_product_provider.h"

#include <cstdint>
#include <optional>
#include <string>
#include <vector>

namespace game_price {

class SteamProvider final : public StoreProductProvider {
public:
    explicit SteamProvider(const std::string& dataPath);
    Store store() const noexcept override;
    std::vector<StoreProduct> findProducts(const std::string& gameId) const override;

private:
    struct RawProduct {
        std::string appId;
        std::string gameId;
        std::optional<std::int64_t> regularPriceWon;
        std::int64_t finalPriceWon{};
        int discountPercent{};
        std::string platformFlags;
        bool available{false};
        std::optional<std::string> observedAt;
    };

    std::vector<RawProduct> products_;
};

}  // namespace game_price
