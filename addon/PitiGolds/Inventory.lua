-- Inventario: bolsas, banco, banco de banda guerrera, correo y lo que envías
-- por correo a tus otros personajes.
local ADDON, ns = ...

-- Listas de contenedores --------------------------------------------------------

local function SortedKeys(set)
  local list = {}
  for k in pairs(set) do list[#list + 1] = k end
  table.sort(list)
  return list
end

-- Devuelve los índices de bolsa que lleva encima, los del banco del personaje y
-- los del banco de banda guerrera. Se leen de Enum.BagIndex porque los números
-- cambian entre versiones del cliente.
local function BagLists()
  local carried, bank, warband = {}, {}, {}
  local lastCarried = NUM_TOTAL_EQUIPPED_BAG_SLOTS or ((NUM_BAG_SLOTS or 4) + 1)
  for bag = 0, lastCarried do carried[bag] = true end
  if Enum and Enum.BagIndex then
    for name, index in pairs(Enum.BagIndex) do
      if type(name) == "string" and type(index) == "number" and not carried[index] then
        if name:find("Account") then
          warband[index] = true
        elseif name:find("[Bb]ank") then
          bank[index] = true
        end
      end
    end
  else
    bank[BANK_CONTAINER or -1] = true
    bank[REAGENTBANK_CONTAINER or -3] = true
    for bag = lastCarried + 1, lastCarried + (NUM_BANKBAGSLOTS or 7) do bank[bag] = true end
  end
  return SortedKeys(carried), SortedKeys(bank), SortedKeys(warband)
end

local function ScanBags(bags)
  local items, bound = {}, {}
  local slots, free = 0, 0
  for _, bag in ipairs(bags) do
    local n = C_Container.GetContainerNumSlots(bag) or 0
    slots = slots + n
    for slot = 1, n do
      local info = C_Container.GetContainerItemInfo(bag, slot)
      if info and info.itemID then
        local target = info.isBound and bound or items
        target[info.itemID] = (target[info.itemID] or 0) + (info.stackCount or 1)
        if info.hyperlink then ns.NoteItemName(info.itemID, info.hyperlink:match("%[(.-)%]")) end
      else
        free = free + 1
      end
    end
  end
  return { items = items, bound = bound, slots = slots, free = free, updated = time() }
end

-- Bolsas y banco -----------------------------------------------------------------

function ns.ScanCarried()
  local carried = BagLists()
  ns.Char().inventory.bags = ScanBags(carried)
end

local function ScanBank()
  if not ns.bankOpen then return end
  local _, bank, warband = BagLists()
  local c = ns.Char()
  local bankData = ScanBags(bank)
  if bankData.slots > 0 then c.inventory.bank = bankData end
  local warbandData = ScanBags(warband)
  if warbandData.slots > 0 then PitiGoldsDB.account.warbandBank = warbandData end
end

local function IsBankInteraction(kind)
  local P = Enum and Enum.PlayerInteractionType
  return P ~= nil and (kind == P.Banker or kind == P.AccountBanker or kind == P.CharacterBanker)
end

local function OnBankOpened()
  ns.bankOpen = true
  -- El contenido del banco tarda un instante en llegar al abrirlo.
  C_Timer.After(0.5, ScanBank)
end

local function OnBankClosed()
  if ns.bankOpen then pcall(ScanBank) end
  ns.bankOpen = false
end

ns.On("BANKFRAME_OPENED", OnBankOpened)
ns.On("BANKFRAME_CLOSED", OnBankClosed)
ns.On("PLAYER_INTERACTION_MANAGER_FRAME_SHOW", function(_, kind)
  if IsBankInteraction(kind) then OnBankOpened() end
end)
ns.On("PLAYER_INTERACTION_MANAGER_FRAME_HIDE", function(_, kind)
  if IsBankInteraction(kind) then OnBankClosed() end
end)

ns.On("BAG_UPDATE_DELAYED", function()
  ns.Debounce("bags", 1, ns.ScanCarried)
  if ns.bankOpen then ns.Debounce("bank", 1, ScanBank) end
end)
ns.On("PLAYERBANKSLOTS_CHANGED", function() ns.Debounce("bank", 1, ScanBank) end)
ns.On("PLAYERREAGENTBANKSLOTS_CHANGED", function() ns.Debounce("bank", 1, ScanBank) end)

ns.On("PLAYER_LOGIN", function()
  C_Timer.After(2, ns.ScanCarried)
end)

-- Correo ---------------------------------------------------------------------------

local function ScanInbox()
  if not ns.mailOpen or not GetInboxNumItems then return end
  local num, total = GetInboxNumItems()
  local items, money, minDays = {}, 0, nil
  local maxAttach = ATTACHMENTS_MAX_RECEIVE or 16
  for i = 1, num do
    local _, _, _, _, mailMoney, codAmount, daysLeft, itemCount = GetInboxHeaderInfo(i)
    money = money + (mailMoney or 0)
    if daysLeft and (not minDays or daysLeft < minDays) then minDays = daysLeft end
    -- Los objetos contra reembolso no son tuyos hasta que pagas.
    if (itemCount or 0) > 0 and (codAmount or 0) == 0 then
      for j = 1, maxAttach do
        local name, itemID, _, count = GetInboxItem(i, j)
        if itemID then
          items[itemID] = (items[itemID] or 0) + (count or 1)
          ns.NoteItemName(itemID, name)
        end
      end
    end
  end
  local inv = ns.Char().inventory
  inv.mail = { items = items, money = money, shown = num, total = total, minDaysLeft = minDays, updated = time() }
  -- Lo que te mandaron tus otros personajes ya aparece en el buzón.
  inv.mailIncoming = nil
end

local function OnMailOpened()
  ns.mailOpen = true
  ns.Debounce("mail", 1, ScanInbox)
end

local function OnMailClosed()
  if ns.mailOpen then pcall(ScanInbox) end
  ns.mailOpen = false
end

local function IsMailInteraction(kind)
  local P = Enum and Enum.PlayerInteractionType
  return P ~= nil and kind == P.MailInfo
end

ns.On("MAIL_SHOW", OnMailOpened)
ns.On("MAIL_CLOSED", OnMailClosed)
ns.On("PLAYER_INTERACTION_MANAGER_FRAME_SHOW", function(_, kind)
  if IsMailInteraction(kind) then OnMailOpened() end
end)
ns.On("PLAYER_INTERACTION_MANAGER_FRAME_HIDE", function(_, kind)
  if IsMailInteraction(kind) then OnMailClosed() end
end)
ns.On("MAIL_INBOX_UPDATE", function()
  if ns.mailOpen then ns.Debounce("mail", 1, ScanInbox) end
end)

-- Correo enviado a tus otros personajes: se apunta en el destinatario para que
-- sus objetos cuenten aunque todavía no haya abierto el buzón.

local pendingSend

local function FindCharacterKey(recipient)
  if not recipient or recipient == "" then return nil end
  if not recipient:find("-", 1, true) then
    recipient = recipient .. "-" .. (GetNormalizedRealmName() or "")
  end
  local wanted = recipient:lower()
  for key in pairs(PitiGoldsDB.characters) do
    if key:lower() == wanted then return key end
  end
end

if SendMail then
  hooksecurefunc("SendMail", function(recipient)
    if not ns.ready then return end
    local items = {}
    for i = 1, (ATTACHMENTS_MAX_SEND or 12) do
      local _, itemID, _, count = GetSendMailItem(i)
      if itemID then items[itemID] = (items[itemID] or 0) + (count or 1) end
    end
    pendingSend = { to = recipient, items = items, money = GetSendMailMoney and GetSendMailMoney() or 0 }
  end)
end

ns.On("MAIL_SEND_SUCCESS", function()
  local sent = pendingSend
  pendingSend = nil
  if not sent then return end
  local key = FindCharacterKey(sent.to)
  if key and key ~= ns.charKey then
    local target = PitiGoldsDB.characters[key]
    target.inventory = target.inventory or {}
    local list = target.inventory.mailIncoming or {}
    list[#list + 1] = { from = ns.charKey, items = sent.items, money = sent.money, time = time() }
    target.inventory.mailIncoming = list
  end
  ns.Debounce("bags", 1, ns.ScanCarried)
end)

ns.On("MAIL_FAILED", function() pendingSend = nil end)
