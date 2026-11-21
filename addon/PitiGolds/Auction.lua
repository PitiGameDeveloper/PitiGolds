-- La casa de subastas: si está abierta, las subastas que tiene puestas el personaje y las
-- búsquedas del botón Buscar (que esperan a que el servidor acepte peticiones).
-- Los precios no salen de aquí: los escanea Auctionator (Auctionator.lua).
local ADDON, ns = ...

-- Envía la petición en cuanto el servidor de subastas acepte mensajes.
local pendingSend
local function SendWhenReady(fn)
  if not C_AuctionHouse.IsThrottledMessageSystemReady or C_AuctionHouse.IsThrottledMessageSystemReady() then
    fn()
  else
    pendingSend = fn
  end
end
ns.AuctionSendWhenReady = SendWhenReady

ns.On("AUCTION_HOUSE_THROTTLED_SYSTEM_READY", function()
  local fn = pendingSend
  if fn then
    pendingSend = nil
    fn()
  end
end)

-- Subastas propias ---------------------------------------------------------------------

local function RecordOwnedAuctions()
  if not C_AuctionHouse.GetNumOwnedAuctions then return end
  local list = {}
  for i = 1, C_AuctionHouse.GetNumOwnedAuctions() do
    local a = C_AuctionHouse.GetOwnedAuctionInfo(i)
    if a and a.itemKey then
      list[#list + 1] = {
        itemID = a.itemKey.itemID,
        qty = a.quantity,
        buyout = a.buyoutAmount,
        bid = a.bidAmount,
        status = a.status,
        timeLeft = a.timeLeftSeconds,
      }
      ns.NoteItem(a.itemKey.itemID, a.itemLink and a.itemLink:match("%[(.-)%]"))
    end
  end
  ns.Char().inventory.auctions = { list = list, updated = time() }
end

ns.On("OWNED_AUCTIONS_UPDATED", RecordOwnedAuctions)

-- Apertura y cierre de la subasta -------------------------------------------------------

local function OnAuctionHouseOpened()
  if ns.ahOpen then return end
  ns.ahOpen = true
  if ns.ShowAuctionButtons then ns.ShowAuctionButtons() end
  if ns.Auctionator then ns.Auctionator.Warn() end
  C_Timer.After(1, function()
    if ns.ahOpen and C_AuctionHouse.QueryOwnedAuctions then
      pcall(C_AuctionHouse.QueryOwnedAuctions, {})
    end
  end)
end

local function OnAuctionHouseClosed()
  if not ns.ahOpen then return end
  ns.ahOpen = false
  pendingSend = nil
  if ns.HideAuctionButtons then ns.HideAuctionButtons() end
end

local function IsAuctionInteraction(kind)
  local P = Enum and Enum.PlayerInteractionType
  return P ~= nil and kind == P.Auctioneer
end

ns.On("AUCTION_HOUSE_SHOW", OnAuctionHouseOpened)
ns.On("AUCTION_HOUSE_CLOSED", OnAuctionHouseClosed)
ns.On("PLAYER_INTERACTION_MANAGER_FRAME_SHOW", function(_, kind)
  if IsAuctionInteraction(kind) then OnAuctionHouseOpened() end
end)
ns.On("PLAYER_INTERACTION_MANAGER_FRAME_HIDE", function(_, kind)
  if IsAuctionInteraction(kind) then OnAuctionHouseClosed() end
end)
