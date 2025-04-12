# Running Joinmarket Scenarios

This command runs a scenario using Joinmarket with both taker and maker wallets. In this example, the scenario contains two takers (using tumbler mode) and two makers.

```bash
python manager.py --engine joinmarket run --scenario scenarios/joinmarket/taker_2_maker_10.json
```

## Joinmarket Configuration
The environment deployes joinmarket-client-server dockerized implementations. The Joinmarket configuration is set in the `joinmarket-client-server` container. 
The configuration file is located at `/containers/joinmarket-client-server/jmclient.cfg`. 
The images are cached and need to be rebuilt to apply changes to the configuration.

### Changes from the default Joinmarket configuration (that affect the wallet behavior):    
- The `maker_timeout` value is set to 30 seconds (default 60 seconds). This value is also used to calculate the tumbler restart timer. Tumbler restart = maker_timeout * 20 (5 minutes).

### Supported Features
- Makers running yield generator.
- Takers creating coinjoin transactions (repeated in fixed time intervals).
- Takers using tumbler mode for scheduling coinjoins.
- Sourcing commitments from takers (joinmarket-default).

### Unsupported Features
- Fidelity bonds are not supported at the moment.

## Scenario File
The scenario file follows a structure similar to the Wasabi scenario but with additional fields for individual wallet settings.

### Wallets Configuration

Each wallet configuration is a JSON object with these keys:

- **`funds`**  
  A list indicating the funds available for coinjoins. Each element can be an integer (representing satoshis) or an object with:
  - `value`: Amount (in satoshis) to use.
  - `delay_blocks`: Number of blocks to wait before sending funds.
  - `delay_rounds`: Number of coinjoin rounds to delay fund delivery.

- **`type`**  
  Specifies the wallet role: either `"taker"` or `"maker"`.

- **`offers`**  
  For maker wallets, an array of offer objects defining fee parameters and size limits. (See below for details.)

- **`tumbler_options`**  
  For taker wallets using tumbler mode, this object controls the scheduling and parameters for coinjoin transactions. (See the section below for details.)

### Taker Offers

A taker can also be run individually (without using tumbler scheduling) by specifying parameters such as delay_blocks, time_between_rounds, and an explicit list of offers. In this mode, the wallet directly controls each coinjoin round. For example:

{
  "funds": [3000000],
  "type": "taker",
  "delay_blocks": 10,
  "time_between_rounds": 10,
  "offers": [
    {
      "mixdepth": 0,
      "amount_sats": 40000,
      "counterparties": 4
    }
  ]
}

In this configuration:

    delay_blocks defines the number of blocks to wait before starting.
    time_between_rounds specifies the time (in minutes) between coinjoin rounds.
    offers contains the parameters for each coinjoin (here, using mixdepth 0, sending 40,000 satoshis, and targeting 4 counterparties).


### Maker Offers

Maker wallets include an `offers` field that is an array of offer objects. Each maker offer includes:

- **`txfee`**: Fixed transaction fee component (in satoshis).  
- **`cjfee_a`**: Absolute coinjoin fee (in satoshis).  
- **`cjfee_r`**: Relative coinjoin fee (as a fraction).  
- **`ordertype`**: The order type (e.g., `"sw0reloffer"`).  
- **`minsize`**: Minimum coinjoin size accepted (in satoshis).  
- **`maxsize`**: Maximum coinjoin size accepted (in satoshis).

For example, a maker offer might look like this:

```json
{
  "txfee": 0,
  "cjfee_a": 5000,
  "cjfee_r": 0.00004,
  "ordertype": "sw0reloffer",
  "minsize": 30000,
  "maxsize": 3000000
}
```

### Tumbler Options

For taker wallets running in tumbler mode, the `tumbler_options` object controls how coinjoins are scheduled. Below is a table summarizing each parameter:

| Parameter                    | Basic Concise Description                                           | Joinmarket Default | Used Scenario Default | Used Scenario Note                                                                                           |
|------------------------------|---------------------------------------------------------------------|--------------------|-----------------------|--------------------------------------------------------------------------------------------------------------|
| `addrcount`                  | Number of destination addresses for outputs                         | 3                  | 3                     | –                                                                                                            |
| `minmakercount`              | Minimum maker counterparties per coinjoin                           | 4                  | 4                     | –                                                                                                            |
| `makercountrange`            | Range of makers as `[mean, spread]`                                 | [9, 1]             | [5, 1]                | Reduced from default for smaller simulations                                                                 |
| `mixdepthcount`              | Number of wallet mixdepths used                                     | 4                  | 3                     | –                                                                                                            |
| `mintxcount`                 | Minimum coinjoin transactions per mixdepth                          | 2                  | 2                     | –                                                                                                            |
| `txcountparams`              | Normal distribution parameters for tx count per mixdepth            | [2, 1]             | [3, 1]                | –                                                                                                            |
| `timelambda`                 | Avg. time (minutes) between transactions (exponential distribution) | 60                 | 5                     | As short as possible for swift simulation, yet long enough for 5 blocks to pass (ensuring UTXO confirmation) |
| `stage1_timelambda_increase` | Multiplier for stage 1 wait time vs stage 2                         | 3                  | 1                     | –                                                                                                            |
| `liquiditywait`              | Wait time (seconds) after failed order selection                    | 60                 | 60                    | –                                                                                                            |
| `waittime`                   | Wait time (seconds) for incoming orders                             | 20                 | 20                    | –                                                                                                            |
| `mixdepthsrc`                | Source mixdepth index                                               | 0                  | 0                     | –                                                                                                            |
| `restart`                    | Resume from an existing schedule file                               | false              | true                  | –                                                                                                            |
| `mincjamount`                | Minimum coinjoin amount (satoshis)                                  | 100,000            | 35,000                | Must correspond with makers; if too low, split amounts may trigger insufficient liquidity errors             |
| `amtmixdepths`               | Total number of mixdepths used (deprecated)                         | -1                 | 4                     | –                                                                                                            |
| `rounding_chance`            | Probability of rounding non-sweep coinjoin amounts                  | 0.25               | 0                     | –                                                                                                            |
| `rounding_sigfig_weights`    | Weights for rounding to 1–5 significant figures                     | [55,15,25,65,40]   | [55,15,25,65,45]      | –                                                                                                            |



**Notes:**
- The defaults shown above are for reference. The example scenario below uses the following tumbler settings:
- The values have been tested with reduced block times to 30-45 seconds from the default 30 - 90 seconds to speed up the sourcing commitments. If run with the default block time, the `timelambda` value should be increased.
- (The configuration is hardcoded in the btc-node mine.sh script and the image needs to be rebuilt to change the block time.)
```bash
    sleep $(($RANDOM % 15 + 30)) # Reduced to 30-45 seconds to speed up joinmarket sourcing commitments
```
- The maker_timeout value in the Joinmarket configuration is set to 30 seconds (default 60 seconds). The tumbler restart timer depends on this value. Tumbler restart = maker_timeout * 20 (5 minutes). For short simulations, it is \
recommended to set the timelambda value in a way that restarts will occur as little as possible. 

```json
{
  "addrcount": 3,
  "minmakercount": 4,
  "makercountrange": [5, 1],
  "mixdepthcount": 3,
  "mintxcount": 2,
  "txcountparams": [3, 1],
  "timelambda": 5,
  "stage1_timelambda_increase": 1,
  "liquiditywait": 60,
  "waittime": 20,
  "mixdepthsrc": 0,
  "restart": true,
  "mincjamount": 35000,
  "amtmixdepths": 4,
  "rounding_chance": 0,
  "rounding_sigfig_weights": [55, 15, 25, 65, 45]
}
```

## Logs

- coins.json, keys.json and unspent_coins.json contain information in wasabi wallet format
- `joinmarket/jmwalletd.log` contains all logs from joinmarket
  - For maker:
    - `obtained tx` in process of the coinjoin
    - `Added utxos:` indicate successful coinjoin
  - For taker:
    - successful coinjoins are logged as `Coinjoin completed correctly`
    - failed coinjoins are logged as `Coinjoin did not complete successfully`.
    - Sources of failure:
      - `Failed to source a commitment`
      - `Makers who didnt respond: [`
  - For tumbler additionaly:
    - Retries: `Stall detected`
    - `NotEnoughFundsException` Remaining funds are lower than the minimum coinjoin amount, the amount gets increased but the taker does not have the funds to cover the increase.
    - `INFO:Failed to source a commitment` Transaction initiated too early, the utxos do not have 5 confirmations.
- `joinmarket/.joinmarket/logs`
  - `JXXXX.log` contains logs for each script run, content same as in `jmwalletd.log`
  - `TUMBLE.log` contains concise information about the tumbler coinjoins
  - `TUMBLE.schedule` contains the schedule for the tumbler, updated
  - `yigen-statement.csv` should contains the yield generator info, does not seem to work properly