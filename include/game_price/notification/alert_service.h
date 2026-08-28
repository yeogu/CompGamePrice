#pragma once

#include "game_price/notification/account_repository.h"

#include <string>

namespace game_price {

class AlertService {
public:
    explicit AlertService(AccountRepository& repository);
    std::size_t evaluateGame(const std::string& gameId) const;
private:
    AccountRepository& repository_;
};

}  // namespace game_price
