# Test Plan for buy_sltp/sell_sltp

## 1. TEST SCENARIOS LIST

### Group A: Basic Order Placement

#### A1. Simple Entry Variants
- **A1.1**: Market entry, one stop, one take profit
- **A1.2**: Limit entry (single order), one stop, one take profit
- **A1.3**: Multiple limit entries, one stop, one take profit

#### A2. Multiple Stops/Takes
- **A2.1**: Market entry, multiple stops (equal shares), multiple takes (equal shares)
- **A2.2**: Market entry, multiple stops (custom shares), multiple takes (custom shares)
- **A2.3**: Limit entry, multiple stops, multiple takes
- **A2.4**: Multiple limit entries, multiple stops, multiple takes

#### A3. Variants Without Stops or Takes
- **A3.1**: Market entry, only stops (no take profits)
- **A3.2**: Market entry, only take profits (no stops)
- **A3.3**: Limit entry, only stops
- **A3.4**: Limit entry, only take profits
- **A3.5**: Multiple limit entries, only stops
- **A3.6**: Multiple limit entries, only take profits

#### A4. modify_deal - Basic Modification
- **A4.1**: A3.6 scenario → modify_deal to update stop loss and take profit
  - Place buy_sltp with multiple limit entries, only take profits
  - After entries execute, modify_deal to add stop loss and update take profit
  - Verify new orders are placed, old active orders are canceled
  - Verify position volume is preserved

---

### Group B: Order Execution - Simple Cases

#### B1. Single Order Execution
- **B1.1**: Market entry → stop triggers (price hits only stop)
- **B1.2**: Market entry → take profit triggers (price hits only take profit)
- **B1.3**: Limit entry → entry triggers → stop triggers
- **B1.4**: Limit entry → entry triggers → take profit triggers

#### B2. Multiple Same-Type Orders Execution on Same Bar
- **B2.1**: Market entry → multiple stops trigger simultaneously (price hits all stops)
- **B2.2**: Market entry → multiple take profits trigger simultaneously (price hits all takes)
- **B2.3**: Multiple limit entries → all trigger simultaneously
- **B2.4**: Market entry → multiple stops trigger sequentially (on different bars)
- **B2.5**: Market entry → multiple take profits trigger sequentially (on different bars)

#### B3. Partial Execution of Same-Type Orders
- **B3.1**: Market entry → multiple stops, only one triggers (price hits one stop)
- **B3.2**: Market entry → multiple stops, part triggers (price hits part of stops)
- **B3.3**: Market entry → multiple take profits, only one triggers
- **B3.4**: Market entry → multiple take profits, part triggers
- **B3.5**: Multiple limit entries → only one triggers
- **B3.6**: Multiple limit entries → part triggers

#### B4. modify_deal - After Partial Execution
- **B4.1**: B3.6 scenario → modify_deal to update remaining orders
  - Place buy_sltp with multiple limit entries
  - Part of entries trigger
  - modify_deal to update stop loss and take profit for remaining position
  - Verify new orders are placed with correct volumes based on remaining position
  - Verify executed orders remain unchanged

---

### Group C: Order Execution - Complex Cases (Entries + Stops Simultaneously)

#### C1. One Entry, One Stop
- **C1.1**: Limit entry and stop hit simultaneously → both trigger
- **C1.2**: Market entry → on next bar entry and stop hit simultaneously

#### C2. One Entry, Multiple Stops
- **C2.1**: Limit entry and all stops hit simultaneously → entry + all stops trigger
- **C2.2**: Limit entry and part of stops hit simultaneously → entry + part of stops trigger
- **C2.3**: Market entry → on next bar entry (already executed) and all stops hit simultaneously

#### C3. Multiple Entries, All Stops
- **C3.1**: Multiple limit entries and all stops hit simultaneously → all entries + all stops trigger
- **C3.2**: Multiple limit entries and all stops hit simultaneously → part of entries + all stops trigger

#### C4. Multiple Entries, Part of Stops
- **C4.1**: Multiple limit entries and part of stops hit simultaneously → all entries + part of stops
- **C4.2**: Multiple limit entries and part of stops hit simultaneously → part of entries + part of stops

#### C5. modify_deal - After Complex Execution
- **C5.1**: C4.2 scenario → modify_deal to update remaining orders
  - Place buy_sltp with multiple limit entries and multiple stops
  - Part of entries and part of stops trigger simultaneously
  - modify_deal to update remaining stop loss and take profit
  - Verify new orders are placed with correct volumes based on remaining position
  - Verify executed orders remain unchanged

---

### Group D: Order Execution - Complex Cases (Entries + Takes Simultaneously)

#### D1. One Entry, One Take Profit
- **D1.1**: Limit entry and take profit hit simultaneously → both trigger

#### D2. One Entry, Multiple Take Profits
- **D2.1**: Limit entry and all take profits hit simultaneously → entry + all takes trigger
- **D2.2**: Limit entry and part of take profits hit simultaneously → entry + part of takes trigger

#### D3. Multiple Entries, All Take Profits
- **D3.1**: Multiple limit entries and all take profits hit simultaneously → all entries + all takes

#### D4. Multiple Entries, Part of Take Profits
- **D4.1**: Multiple limit entries and part of take profits hit simultaneously → all entries + part of takes
- **D4.2**: Multiple limit entries and part of take profits hit simultaneously → part of entries + part of takes

#### D5. modify_deal - After Take Profit Execution
- **D5.1**: D4.2 scenario → modify_deal to update remaining orders
  - Place buy_sltp with multiple limit entries and multiple take profits
  - Part of entries and part of take profits trigger simultaneously
  - modify_deal to update remaining stop loss and take profit
  - Verify new orders are placed with correct volumes based on remaining position
  - Verify executed orders remain unchanged

---

### Group E: Order Execution - Most Complex Cases (Entries + Stops + Takes Simultaneously)

**IMPORTANT RULE**: When price hits both stops and take profits simultaneously, only stops are considered. Take profits may trigger on subsequent bars if the deal is not fully closed.

**Volume Calculation Rules for Stop Loss and Take Profit Orders**:

1. **Stop Loss Volume Calculation**:
   - Stop loss volumes are calculated from the **entry volume** (sum of all entry order volumes), **minus executed take profit volumes**
   - Each stop loss order's volume is calculated by applying its fraction to the target volume
   - The last (extreme) stop loss order always closes all remaining volume

2. **Take Profit Volume Calculation**:
   - Take profit volumes are calculated from the **entry volume** (sum of all entry order volumes), **minus executed stop loss volumes**
   - Each take profit order's volume is calculated by applying its fraction to the target volume
   - The last (extreme) take profit order always closes all remaining volume

3. **Key Points**:
   - Both stop loss and take profit volumes are always calculated from the **full entry volume**, not from the current position size
   - When calculating stop loss volumes, executed take profits are subtracted from the entry volume
   - When calculating take profit volumes, executed stop losses are subtracted from the entry volume
   - The last order (extreme stop or extreme take) always closes all remaining volume to ensure the position is fully closed

#### E1. One Entry, One Stop, One Take Profit
- **E1.1**: Limit entry, stop and take profit hit simultaneously → entry + stop trigger, take profit does NOT trigger
- **E1.2**: Limit entry, stop and take profit hit simultaneously → entry + stop trigger, take profit triggers on next bar (if deal didn't close completely)

#### E2. One Entry, Multiple Stops, One Take Profit
- **E2.1**: Limit entry, all stops and take profit hit simultaneously → entry + all stops trigger, take profit does NOT trigger
- **E2.2**: Limit entry, part of stops and take profit hit simultaneously → entry + part of stops trigger, take profit does NOT trigger

#### E3. One Entry, One Stop, Multiple Take Profits
- **E3.1**: Limit entry, stop and all take profits hit simultaneously → entry + stop trigger, all takes do NOT trigger
- **E3.2**: Limit entry, stop and all take profits hit simultaneously → entry + stop trigger, part of takes trigger on next bar (if deal didn't close completely)

#### E4. One Entry, Multiple Stops, Multiple Take Profits
- **E4.1**: Limit entry, all stops and all take profits hit simultaneously → entry + all stops trigger, all takes do NOT trigger
- **E4.2**: Limit entry, all stops and part of take profits hit simultaneously → entry + all stops trigger, part of takes do NOT trigger
- **E4.3**: Limit entry, part of stops and all take profits hit simultaneously → entry + part of stops trigger, all takes do NOT trigger
- **E4.4**: Limit entry, part of stops and part of take profits hit simultaneously → entry + part of stops trigger, part of takes do NOT trigger

#### E5. Multiple Entries, Stops, Take Profits
- **E5.1**: Multiple limit entries, all stops and all take profits hit simultaneously → all entries + all stops trigger, all takes do NOT trigger
- **E5.2**: Multiple limit entries, all stops and part of take profits hit simultaneously → all entries + all stops trigger, part of takes do NOT trigger
- **E5.3**: Multiple limit entries, part of stops and all take profits hit simultaneously → all entries + part of stops trigger, all takes do NOT trigger
- **E5.4**: Multiple limit entries, part of stops and part of take profits hit simultaneously → all entries + part of stops trigger, part of takes do NOT trigger

#### E6. modify_deal - After Most Complex Execution
- **E6.1**: E5.4 scenario → modify_deal to update remaining orders
  - Place buy_sltp with multiple limit entries, multiple stops, and multiple take profits
  - Part of entries, part of stops, and part of take profits hit simultaneously
  - modify_deal to update remaining stop loss and take profit
  - Verify new orders are placed with correct volumes based on remaining position
  - Verify executed orders remain unchanged
  - Verify stop priority logic is maintained

---

### Group F: Validation and Errors

#### F1. Price Validation
- **F1.1**: BUY stop loss above current price → validation error
- **F1.2**: BUY take profit below current price → validation error
- **F1.3**: SELL stop loss below current price → validation error
- **F1.4**: SELL take profit above current price → validation error
- **F1.5**: BUY limit entry above current price → validation error
- **F1.6**: SELL limit entry below current price → validation error

#### F2. Entry Limit Protection by Stop Loss
- **F2.1**: BUY single limit entry below minimum stop price → validation error (entry not protected)
- **F2.2**: SELL single limit entry above maximum stop price → validation error (entry not protected)
- **F2.3**: BUY multiple limit entries, one entry below minimum stop price → validation error
- **F2.4**: SELL multiple limit entries, one entry above maximum stop price → validation error
- **F2.5**: BUY limit entry equal to minimum stop price → validation error (entry not protected, stop must be strictly below)
- **F2.6**: SELL limit entry equal to maximum stop price → validation error (entry not protected, stop must be strictly above)

#### F3. Structure Validation
- **F3.1**: Sum of stop shares != 1.0 → validation error
- **F3.2**: Sum of take profit shares != 1.0 → validation error
- **F3.3**: Sum of entry order shares != 1.0 → validation error
- **F3.4**: Negative shares → validation error
- **F3.5**: Shares > 1.0 → validation error

---

### Group G: Edge Cases

#### G1. Full Position Closure
- **G1.1**: Market entry → all stops trigger → deal fully closed
- **G1.2**: Market entry → all take profits trigger → deal fully closed
- **G1.3**: Market entry → part of stops trigger → remaining part closed by last stop
- **G1.4**: Market entry → part of take profits trigger → remaining part closed by last take profit

#### G2. Partial Position Closure
- **G2.1**: Market entry → one stop out of several triggers → position partially closed, other stops remain active
- **G2.2**: Market entry → one take profit out of several triggers → position partially closed, other takes remain active

#### G4. Unclosed Deals at End of Test
- **G4.1**: Market entry, only stops → stops don't trigger → deal remains open → automatic closure at end of testing
- **G4.2**: Market entry, only take profits → takes don't trigger → deal remains open → automatic closure at end of testing
- **G4.3**: Market entry, stops and take profits → part of stops trigger, part of takes don't trigger → deal partially closed → automatic closure of remainder at end of testing

**IMPORTANT**: In tests where a deal may remain open (e.g., tests without take profits where stops don't trigger), the backtester will automatically close the deal at the end of testing. This is important to consider when checking results - need to verify that automatic closure occurred correctly.

#### G3. Order Cancellation
- **G3.1**: Market entry → stops/takes set → entry executed → cancel stops/takes → verify cancellation
- **G3.2**: Limit entry → entry not executed → cancel entry order → verify cancellation

#### G5. modify_deal - Edge Cases
- **G5.1**: G3.2 scenario → modify_deal to modify deal with unexecuted limit entry
  - Place buy_sltp with limit entry (not executed)
  - modify_deal to update stop loss and take profit
  - Verify unexecuted entry order is canceled
  - Verify new orders are placed
  - Verify position volume is preserved (0 if entry didn't execute)
- **G5.2**: modify_deal with enter=None (only update exits)
  - Place buy_sltp with market entry, stop loss, take profit
  - Entry executes
  - modify_deal with enter=None, update stop loss and take profit
  - Verify no new entry orders, only exit orders updated
  - Verify position volume is preserved
- **G5.3**: modify_deal with negative enter (close part of position)
  - Place buy_sltp with market entry, stop loss, take profit
  - Entry executes (position = 1.0)
  - modify_deal with enter=-0.3 (close 0.3), update stop loss and take profit
  - Verify market order to close 0.3 is placed
  - Verify position volume decreases to 0.7
  - Verify new exit orders are calculated based on remaining position
- **G5.4**: modify_deal with positive enter (add to position)
  - Place buy_sltp with market entry, stop loss, take profit
  - Entry executes (position = 1.0)
  - modify_deal with enter=0.5 (add 0.5), update stop loss and take profit
  - Verify new entry order is placed
  - Verify position volume increases to 1.5 after new entry executes
  - Verify new exit orders are calculated based on total position

---

### Group H: Interleaved Entry and Exit Orders

**NOTE**: This group tests scenarios where exit orders (stops or take profits) are positioned between entry orders, creating an interleaved structure. This tests the protection logic and execution order when exit orders are not simply above/below all entries.

#### H1. Stops Between Entries - Alternating Single Orders
- **H1.1**: BUY - Multiple limit entries with stops between them (alternating pattern: entry, stop, entry, stop, entry)
  - Example: entries at 100.0, 90.0, 80.0; stops at 95.0, 85.0
  - Verify all entries are protected (all entries > min_stop)
  - Test execution when price hits entries and stops in various combinations
- **H1.2**: SELL - Multiple limit entries with stops between them (alternating pattern: entry, stop, entry, stop, entry)
  - Example: entries at 100.0, 110.0, 120.0; stops at 105.0, 115.0
  - Verify all entries are protected (all entries < max_stop)
  - Test execution when price hits entries and stops in various combinations

#### H2. Stops Between Entries - Alternating Multiple Orders
- **H2.1**: BUY - Multiple limit entries with multiple stops between them (alternating pattern: 2 entries, 2 stops, 2 entries, 2 stops, etc.)
  - Example: entries at 100.0, 95.0, 85.0, 80.0; stops at 92.5, 87.5, 77.5
  - Verify all entries are protected
  - Test execution when price hits entries and stops in various combinations
- **H2.2**: SELL - Multiple limit entries with multiple stops between them (alternating pattern: 2 entries, 2 stops, 2 entries, 2 stops, etc.)
  - Example: entries at 100.0, 105.0, 115.0, 120.0; stops at 107.5, 112.5, 122.5
  - Verify all entries are protected
  - Test execution when price hits entries and stops in various combinations

#### H3. Take Profits Between Entries - Alternating Single Orders
- **H3.1**: BUY - Multiple limit entries with take profits between them (alternating pattern: entry, take, entry, take, entry)
  - Example: entries at 100.0, 90.0, 80.0; take profits at 105.0, 95.0
  - Test execution when price hits entries and take profits in various combinations
- **H3.2**: SELL - Multiple limit entries with take profits between them (alternating pattern: entry, take, entry, take, entry)
  - Example: entries at 100.0, 110.0, 120.0; take profits at 95.0, 105.0
  - Test execution when price hits entries and take profits in various combinations

#### H4. Take Profits Between Entries - Alternating Multiple Orders
- **H4.1**: BUY - Multiple limit entries with multiple take profits between them (alternating pattern: 2 entries, 2 takes, 2 entries, 2 takes, etc.)
  - Example: entries at 100.0, 95.0, 85.0, 80.0; take profits at 102.5, 97.5, 87.5
  - Test execution when price hits entries and take profits in various combinations
- **H4.2**: SELL - Multiple limit entries with multiple take profits between them (alternating pattern: 2 entries, 2 takes, 2 entries, 2 takes, etc.)
  - Example: entries at 100.0, 105.0, 115.0, 120.0; take profits at 97.5, 102.5, 112.5
  - Test execution when price hits entries and take profits in various combinations

#### H5. modify_deal - Interleaved Orders
- **H5.1**: H4.2 scenario → modify_deal to update interleaved orders
  - Place sell_sltp with multiple limit entries and multiple take profits between them
  - modify_deal to update stop loss and take profit
  - Verify new orders maintain protection logic for all entries
  - Verify position volume is preserved
  - Test execution when price hits entries and updated exits in various combinations

---

### Group I: modify_deal Tests

Tests for the `modify_deal()` method that modifies existing deals by canceling active orders and placing new ones.

#### I1. modify_deal Validation
- **I1.1**: modify_deal - deal not found (invalid deal_id) → validation error
- **I1.2**: modify_deal - deal already closed (quantity == 0) → validation error
- **I1.3**: modify_deal - negative volume exceeds current position volume → validation error
- **I1.4**: modify_deal LONG - buy limit order price above current price → validation error
- **I1.5**: modify_deal SHORT - sell limit order price below current price → validation error
- **I1.6**: modify_deal LONG - stop loss trigger price above current price → validation error
- **I1.7**: modify_deal SHORT - stop loss trigger price below current price → validation error
- **I1.8**: modify_deal LONG - take profit price below current price → validation error
- **I1.9**: modify_deal SHORT - take profit price above current price → validation error
- **I1.10**: modify_deal LONG - buy limit entry not protected by stop loss → validation error
- **I1.11**: modify_deal SHORT - sell limit entry not protected by stop loss → validation error

#### I2. modify_deal - Basic Modification
- **I2.1**: A4.1 scenario → modify_deal to update stop loss and take profit
  - Place buy_sltp with multiple limit entries, only take profits
  - After entries execute, modify_deal to add stop loss and update take profit
  - Verify new orders are placed, old active orders are canceled
  - Verify position volume is preserved

#### I3. modify_deal - After Partial Execution
- **I3.1**: B4.1 scenario → modify_deal to update remaining orders
  - Place buy_sltp with multiple limit entries
  - Part of entries trigger
  - modify_deal to update stop loss and take profit for remaining position
  - Verify new orders are placed with correct volumes based on remaining position
  - Verify executed orders remain unchanged

#### I4. modify_deal - After Complex Execution
- **I4.1**: C5.1 scenario → modify_deal to update remaining orders
  - Place buy_sltp with multiple limit entries and multiple stops
  - Part of entries and part of stops trigger simultaneously
  - modify_deal to update remaining stop loss and take profit
  - Verify new orders are placed with correct volumes based on remaining position
  - Verify executed orders remain unchanged

#### I5. modify_deal - After Take Profit Execution
- **I5.1**: D5.1 scenario → modify_deal to update remaining orders
  - Place buy_sltp with multiple limit entries and multiple take profits
  - Part of entries and part of take profits trigger simultaneously
  - modify_deal to update remaining stop loss and take profit
  - Verify new orders are placed with correct volumes based on remaining position
  - Verify executed orders remain unchanged

#### I6. modify_deal - After Most Complex Execution
- **I6.1**: E6.1 scenario → modify_deal to update remaining orders
  - Place buy_sltp with multiple limit entries, multiple stops, and multiple take profits
  - Part of entries, part of stops, and part of take profits hit simultaneously
  - modify_deal to update remaining stop loss and take profit
  - Verify new orders are placed with correct volumes based on remaining position
  - Verify executed orders remain unchanged
  - Verify stop priority logic is maintained

#### I7. modify_deal - Edge Cases
- **I7.1**: modify_deal with unexecuted limit entry
  - Place buy_sltp with limit entry (not executed)
  - modify_deal to update stop loss and take profit
  - Verify unexecuted entry order is canceled
  - Verify new orders are placed
  - Verify position volume is preserved (0 if entry didn't execute)
- **I7.2**: modify_deal with enter=None (only update exits)
  - Place buy_sltp with market entry, stop loss, take profit
  - Entry executes
  - modify_deal with enter=None, update stop loss and take profit
  - Verify no new entry orders, only exit orders updated
  - Verify position volume is preserved
- **I7.3**: modify_deal with negative enter (close part of position)
  - Place buy_sltp with market entry, stop loss, take profit
  - Entry executes (position = 1.0)
  - modify_deal with enter=-0.3 (close 0.3), update stop loss and take profit
  - Verify market order to close 0.3 is placed
  - Verify position volume decreases to 0.7
  - Verify new exit orders are calculated based on remaining position
- **I7.4**: modify_deal with positive enter (add to position)
  - Place buy_sltp with market entry, stop loss, take profit
  - Entry executes (position = 1.0)
  - modify_deal with enter=0.5 (add 0.5), update stop loss and take profit
  - Verify new entry order is placed
  - Verify position volume increases to 1.5 after new entry executes
  - Verify new exit orders are calculated based on total position

#### I8. modify_deal - Interleaved Orders
- **I8.1**: modify_deal to update interleaved orders
  - Place sell_sltp with multiple limit entries and multiple take profits between them
  - modify_deal to update stop loss and take profit
  - Verify new orders maintain protection logic for all entries
  - Verify position volume is preserved
  - Test execution when price hits entries and updated exits in various combinations

---

## 2. DATA TO CHECK

### 2.1. Order Placement Result Check (OrderOperationResult)

#### Result Structure
- `orders`: list of all created orders (entry + exit)
  - Check order count
  - Check order types (MARKET, LIMIT, STOP)
  - Check order sides (BUY, SELL)
  - Check each order's parameters (quantity, price, trigger_price)
- `error_messages`: list of error messages
  - Check absence of errors in successful cases
  - Check presence and content of errors in validation cases
- `active`: list of active order IDs
  - Check match with expected active orders
- `executed`: list of executed order IDs
  - Check absence of executed orders at placement (except market entry)
- `canceled`: list of canceled order IDs
  - Check absence of canceled orders at placement
- `error`: list of order IDs with errors
  - Check absence of errors in successful cases
- `deal_id`: Deal ID
  - Check that deal_id > 0
  - Check that all orders are linked to the same deal
- `volume`: position volume in the deal
  - Check that volume = 0 at placement (before entry orders execute)

#### Detailed Order Check
- **Entry Orders**:
  - Type: MARKET or LIMIT
  - Side: BUY for buy_sltp, SELL for sell_sltp
  - Quantity: matches passed volume
  - Price: for LIMIT - matches passed price, for MARKET - None
  - Trigger_price: None for entry orders
  - Status: ACTIVE (for LIMIT) or EXECUTED (for MARKET)
  - Deal_id: matches deal_id from result

- **Exit Orders (Stops)**:
  - Type: STOP
  - Side: SELL for buy_sltp (closing BUY position), BUY for sell_sltp (closing SELL position)
  - Quantity: matches share of entry (check after entry execution)
  - Price: None for STOP orders
  - Trigger_price: matches passed stop price
  - Status: ACTIVE (stops are set after entry execution)
  - Deal_id: matches deal_id from result

- **Exit Orders (Take Profits)**:
  - Type: LIMIT
  - Side: SELL for buy_sltp, BUY for sell_sltp
  - Quantity: matches share of entry (check after entry execution)
  - Price: matches passed take profit price
  - Trigger_price: None for LIMIT orders
  - Status: ACTIVE (take profits are set after entry execution)
  - Deal_id: matches deal_id from result

---

### 2.2. Order Execution Check

#### Timestamps
- Check execution time of each order (should match the bar on which it triggered)
- Check order execution sequence (entry orders should execute before exit orders)

#### Execution Prices
- **Market Orders**: 
  - For BUY: execution price = current price + slippage
  - For SELL: execution price = current price - slippage
- **Limit Orders**: execution price = order price (if price hit the order)
- **Stop Orders**: 
  - Execute as market orders when trigger_price is hit
  - For BUY stop (SELL side): execution price = trigger_price - slippage
  - For SELL stop (BUY side): execution price = trigger_price + slippage
- Check that prices match expected values considering slippage

#### Execution Volumes
- Check that execution volumes match order volumes
- Check partial executions (if applicable)
- Check that sum of all exit order volumes does not exceed entry volume

#### Order Statuses
- After execution: status = EXECUTED
- Not executed: status = ACTIVE or CANCELED
- Check status transitions

---

### 2.3. Trades Check

#### Trade Structure
- `side`: BUY or SELL
- `price`: execution price
- `quantity`: volume
- `sum`: trade amount (price * quantity)
- `fee`: commission
- `order_id`: ID of order that created the trade
- `deal_id`: Deal ID

#### Trades Check
- Number of trades should match number of executed orders
- For closed position: sum of BUY trade volumes should equal sum of SELL trade volumes (by absolute value)
- Commissions should be calculated correctly:
  - `fee_taker` for market orders and stop orders (which execute as market)
  - `fee_maker` for limit orders
- Prices should account for slippage:
  - For BUY market orders: execution_price = market_price + slippage
  - For SELL market orders: execution_price = market_price - slippage
  - For stop orders: slippage is applied as for market orders
- Each trade should be linked to corresponding order via `order_id`
- Each trade should be linked to deal via `deal_id`

---

### 2.4. Deal Check (Position-Deal)

#### Deal Structure
- `deal_id`: unique ID
- `type`: DealType.LONG or DealType.SHORT (deal type)
- `quantity`: current position volume (positive for LONG, negative for SHORT)
- `avg_buy_price`: average buy price
- `avg_sell_price`: average sell price
- `buy_quantity`: total buy volume
- `buy_cost`: total buy cost
- `sell_quantity`: total sell volume
- `sell_proceeds`: total sell proceeds
- `fee`: total commissions
- `profit`: profit/loss (calculated only for closed deals)
- `orders`: list of all deal orders
- `trades`: list of all trades in this position

#### Deal Check
- **When Opening Position**:
  - `quantity` = sum of entry order volumes (positive for LONG, negative for SHORT)
  - `avg_buy_price` = weighted average of buy prices (if there are BUY trades)
  - `avg_sell_price` = weighted average of sell prices (if there are SELL trades)
  - `buy_quantity` = sum of volumes of all BUY trades
  - `buy_cost` = sum of (price * quantity) of all BUY trades
  - `sell_quantity` = sum of volumes of all SELL trades
  - `sell_proceeds` = sum of (price * quantity) of all SELL trades
  - `fee` = sum of commissions of all trades
  - `profit` = None (deal not yet closed)
  - `is_closed` = False

- **On Partial Closure**:
  - `quantity` changes by volume of closed exit orders (decreases by absolute value)
  - `avg_sell_price` updates (weighted average of all SELL trades)
  - `sell_quantity` increases by volume of closed exit orders
  - `sell_proceeds` increases by sum of closed exit trades
  - `fee` increases by commissions of exit trades
  - `profit` = None (deal not yet fully closed)
  - `is_closed` = False

- **On Full Closure**:
  - `quantity` = 0.0
  - `is_closed` = True
  - `profit` = sell_proceeds - buy_cost - fee (calculated automatically)
  - **IMPORTANT**: Check that `profit` matches expected calculation:
    - For BUY position: profit = (exit_price * volume) - exit_fees - (entry_price * volume + entry_fees)
    - For SELL position: profit = (entry_price * volume - entry_fees) - (exit_price * volume + exit_fees)
    - Account for slippage for market orders and stop orders (which execute as market)
    - Account for fee_taker for market/stop orders and fee_maker for limit orders
  - All exit orders should be executed or canceled

- **Order Links**:
  - All orders (entry + exit) should have the same `deal_id`
  - Check via `broker.get_deal_by_id(deal_id)`

---

### 2.5. Overall Strategy Result Check

#### Equity
- `equity_symbol`: position volume in base currency
  - After full closure = 0.0
  - For open LONG position = positive value (sum of entry order volumes - sum of exit order volumes)
  - For open SHORT position = negative value
- `equity_usd`: balance in USD
  - Changes on each trade
  - For BUY: decreases by (price * quantity + fee)
  - For SELL: increases by (price * quantity - fee)

#### Statistics
- Number of trades
- Number of open/closed deals
- Total profit/loss (sum of `profit` of all closed deals)
- Maximum drawdown
- Check that statistics correctly account for all trades and deals

---

### 2.6. Specific Scenario Checks

#### Simultaneous Multiple Order Triggering
- Check execution order (entry → exit)
- Check that all hit orders triggered
- Check execution prices (should be the same for all orders triggered on the same bar)

#### Stop Priority Over Take Profits
- When price hits both stops and take profits simultaneously:
  - Stops should trigger
  - Take profits should NOT trigger on this bar
  - Take profits may trigger on subsequent bars if position is not fully closed

#### Partial Position Closure
- After partial closure:
  - Remaining stops/takes should remain active
  - Volumes of remaining stops/takes should be recalculated proportionally to remaining position
  - Check that last stop/take closes entire remaining position (regardless of share)

#### Order Cancellation
- After cancellation:
  - Order status = CANCELED
  - Orders should not execute
  - Position should not change

---

## 3. TEST DATA EXAMPLES (Quotes)

**Principle**: Between bars where triggers should occur, bars where no triggers should occur can (but don't have to) be inserted. This makes tests more realistic and verifies that orders don't trigger prematurely.

### For Simple Cases
- Bar 1: price 100.0 (order placement)
- Bar 2: price 98.0 (no triggers)
- Bar 3: price 95.0 (stop trigger)
- Bar 4: price 97.0 (no triggers)
- Bar 5: price 105.0 (take profit trigger)

### For Simultaneous Triggering
- Bar 1: price 100.0 (order placement)
- Bar 2: price 99.0 (no triggers)
- Bar 3: high=110.0, low=90.0 (hits both stop and take profit simultaneously)
- Bar 4: price 100.0 (no triggers, verify that take profits didn't trigger)

### For Sequential Triggering
- Bar 1: price 100.0 (order placement)
- Bar 2: price 98.0 (no triggers)
- Bar 3: low=95.0 (first stop triggers)
- Bar 4: price 94.0 (no triggers)
- Bar 5: low=93.0 (second stop triggers)

### For Partial Triggering
- Bar 1: price 100.0 (order placement)
- Bar 2: price 98.0 (no triggers)
- Bar 3: low=94.0 (hits only one stop out of two, second stop at 92.0)
- Bar 4: price 93.0 (no triggers, second stop not yet hit)
- Bar 5: low=91.0 (second stop triggers)

---

