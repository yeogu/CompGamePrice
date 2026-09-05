#pragma once

#include <string>
#include <optional>
#include <vector>

namespace game_price {

enum class AppCommand {
    Demo,
    Collect,
    CollectSteam,
    CollectSteamAll,
    CollectEpicAll,
    CollectNintendoAll,
    CollectPlayStationAll,
    CollectMicrosoftAll,
    CollectGooglePlayAll,
    CollectAppleAll,
    Compare,
    History,
    CollectionRuns,
    Search,
    SeedDemo,
    Help
};

enum class AppExitCode {
    Success = 0,
    RuntimeError = 1,
    UsageError = 2,
    GameNotFound = 3,
    NoData = 4,
    CollectionFailed = 5
};

struct CommandLineOptions {
    AppCommand command{AppCommand::Demo};
    std::string gameName{"Stardew Valley"};
    std::optional<std::string> historySince;
    std::optional<std::string> dataDirectory;
};

CommandLineOptions parseCommandLine(const std::vector<std::string>& arguments);
std::string commandLineHelp();

}  // namespace game_price
