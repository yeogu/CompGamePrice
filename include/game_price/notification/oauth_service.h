#pragma once

#include "game_price/notification/auth_service.h"

namespace game_price {

class OAuthService {
public:
    explicit OAuthService(AccountRepository& repository);
    AuthResult completeLogin(const OAuthProfile& profile) const;
    ExternalIdentity linkIdentity(std::int64_t userId, const OAuthProfile& profile) const;
private:
    AccountRepository& repository_;
};

}  // namespace game_price
