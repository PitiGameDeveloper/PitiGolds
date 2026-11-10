-- Al pasar el ratón por el oro de las bolsas: el oro de toda la cuenta y el de cada personaje
-- (lo último que vio el addon con cada uno), más el banco de banda.
local ADDON, ns = ...

-- { { nombre, oro, es el actual } ... } de más a menos, y el oro del banco de banda.
function ns.AccountGold()
  local rows = {}
  local db = PitiGoldsDB
  if type(db) ~= "table" then return rows, 0 end
  for key, c in pairs(db.characters or {}) do
    if type(c) == "table" then
      local money = key == ns.charKey and GetMoney() or c.money
      if type(money) == "number" and (money > 0 or key == ns.charKey) then
        rows[#rows + 1] = { ns.CharDisplayName(key, c), money, key == ns.charKey }
      end
    end
  end
  table.sort(rows, function(a, b) return a[2] > b[2] end)
  local warband = db.account and tonumber(db.account.warbandMoney) or 0
  return rows, warband
end

function ns.AddGoldLines(tooltip)
  local rows, warband = ns.AccountGold()
  local total = warband
  for _, row in ipairs(rows) do total = total + row[2] end
  tooltip:AddDoubleLine("Oro de la cuenta", ns.Money(total), 0.9, 0.7, 0.1, 1, 1, 1)
  for _, row in ipairs(rows) do
    local r, g, b = 0.8, 0.8, 0.8
    if row[3] then r, g, b = 0.25, 1, 0.25 end
    tooltip:AddDoubleLine("   " .. row[1], ns.Money(row[2]), r, g, b, 1, 1, 1)
  end
  if warband > 0 then
    tooltip:AddDoubleLine("   Banco de banda", ns.Money(warband), 0.8, 0.8, 0.8, 1, 1, 1)
  end
end

local function ShowGold(frame)
  if not GameTooltip then return end
  -- Si el juego ya enseña su tooltip aquí, se añade debajo; si no, uno nuevo.
  if not (GameTooltip.IsOwned and GameTooltip:IsOwned(frame) and GameTooltip:IsShown()) then
    GameTooltip:SetOwner(frame, "ANCHOR_TOPLEFT")
  else
    GameTooltip:AddLine(" ")
  end
  ns.AddGoldLines(GameTooltip)
  GameTooltip:Show()
end

local hooked = {}
local function Hook(frame)
  if type(frame) ~= "table" or hooked[frame] or not frame.HookScript then return end
  hooked[frame] = true
  if frame.EnableMouse and not (frame.IsMouseEnabled and frame:IsMouseEnabled()) then frame:EnableMouse(true) end
  frame:HookScript("OnEnter", function(self)
    local ok, err = pcall(ShowGold, self)
    if not ok then ns.ReportError("oro de la cuenta", err) end
  end)
  frame:HookScript("OnLeave", function(self)
    if GameTooltip and GameTooltip.IsOwned and GameTooltip:IsOwned(self) then GameTooltip:Hide() end
  end)
  for _, name in ipairs({ "GoldButton", "SilverButton", "CopperButton" }) do Hook(frame[name]) end
end

-- El oro de la mochila: la de bolsas juntas y la mochila suelta.
local function HookBagMoney()
  for _, bag in ipairs({ _G.ContainerFrameCombinedBags, _G.ContainerFrame1 }) do
    if type(bag) == "table" then Hook(bag.MoneyFrame) end
  end
  Hook(_G.ContainerFrame1MoneyFrame)
end

ns.On("PLAYER_LOGIN", function()
  local ok, err = pcall(HookBagMoney)
  if not ok then ns.ReportError("oro de la cuenta", err) end
end)
-- Por si las bolsas se crean más tarde.
ns.On("BAG_OPEN", function() pcall(HookBagMoney) end)
