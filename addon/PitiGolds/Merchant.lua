-- Vendedores: qué venden y a cuánto la unidad, y qué divisas piden (por ejemplo,
-- recetas que se pagan con Merchant's Favor). Sirve para saber qué materiales
-- conviene comprar al vendedor en lugar de en la subasta.
local ADDON, ns = ...

local function ReadMerchantItem(index)
  if C_MerchantFrame and C_MerchantFrame.GetItemInfo then
    local info = C_MerchantFrame.GetItemInfo(index)
    if info then
      return info.name, info.price, info.stackCount, info.numAvailable, info.hasExtendedCost
    end
  end
  if GetMerchantItemInfo then
    local name, _, price, stackCount, numAvailable, _, _, extendedCost = GetMerchantItemInfo(index)
    return name, price, stackCount, numAvailable, extendedCost
  end
end

local function ReadCosts(index)
  if not (GetMerchantItemCostInfo and GetMerchantItemCostItem) then return nil end
  local costs = {}
  for j = 1, GetMerchantItemCostInfo(index) or 0 do
    local _, value, link, currencyName = GetMerchantItemCostItem(index, j)
    costs[#costs + 1] = {
      value = value,
      name = currencyName or (link and link:match("%[(.-)%]")),
      itemID = link and tonumber(link:match("item:(%d+)")),
      currencyID = link and tonumber(link:match("currency:(%d+)")),
    }
  end
  return (#costs > 0) and costs or nil
end

local function ScanMerchant()
  if not ns.merchantOpen or not GetMerchantNumItems then return end
  local vendor = UnitName("npc")
  local known = PitiGoldsDB.vendorItems
  local total = GetMerchantNumItems()
  local sells = {}
  for i = 1, total do
    local itemID = GetMerchantItemID(i)
    local name, price, stack, numAvailable, extended = ReadMerchantItem(i)
    if itemID and name then
      sells[itemID] = true
      ns.NoteItem(itemID, name)
      local entry = {
        price = (price and price > 0) and math.floor(price / math.max(stack or 1, 1)) or nil,
        stack = stack,
        limited = ((numAvailable or -1) >= 0) or nil,
        costs = extended and ReadCosts(i) or nil,
        vendor = vendor,
        -- El precio puede llevar descuentos de este personaje (reputación, talentos de Legacy).
        char = ns.charKey,
        time = time(),
      }
      local old = known[itemID]
      -- Se conserva el vendedor más barato que se haya visto.
      if not old or old.vendor == vendor or not old.price
          or (entry.price and entry.price <= old.price) then
        known[itemID] = entry
      end
    end
  end
  -- Lo que este vendedor vendía y ya no vende (por ejemplo, tras un parche) se borra.
  if total > 0 then
    for itemID, entry in pairs(known) do
      if entry.vendor == vendor and not sells[itemID] then known[itemID] = nil end
    end
  end
end

local function OnMerchantOpened()
  ns.merchantOpen = true
  ns.Debounce("merchant", 0.5, ScanMerchant)
end

local function IsMerchantInteraction(kind)
  local P = Enum and Enum.PlayerInteractionType
  return P ~= nil and kind == P.Merchant
end

ns.On("MERCHANT_SHOW", OnMerchantOpened)
ns.On("MERCHANT_UPDATE", function()
  if ns.merchantOpen then ns.Debounce("merchant", 0.5, ScanMerchant) end
end)
ns.On("MERCHANT_CLOSED", function() ns.merchantOpen = false end)
ns.On("PLAYER_INTERACTION_MANAGER_FRAME_SHOW", function(_, kind)
  if IsMerchantInteraction(kind) then OnMerchantOpened() end
end)
ns.On("PLAYER_INTERACTION_MANAGER_FRAME_HIDE", function(_, kind)
  if IsMerchantInteraction(kind) then ns.merchantOpen = false end
end)
