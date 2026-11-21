-- Precios de la subasta: los de Auctionator. PitiGolds no escanea la subasta; Auctionator lo hace
-- (su botón de escanear y lo que buscas con él) y aquí se leen sus precios:
--   - En partida, al momento (tooltip, ventana de profesión, sesión, cajones y libranzas).
--   - Al salir o con /reload se copia su base de precios a PitiGoldsDB.auctionator para el motor:
--     el último precio mínimo de cada objeto y, por día, el mínimo más bajo, el más alto y cuántas
--     unidades había.
-- Sin Auctionator no hay precios de subasta: se avisa al entrar y al abrir la subasta.
local ADDON, ns = ...

local HISTORY_DAYS = 14   -- días de historial que se copian para el motor
local DAY = 86400

local A = {}
ns.Auctionator = A

local function Database()
  local db = Auctionator and Auctionator.Database
  return type(db) == "table" and db or nil
end

-- ¿Está Auctionator cargado y con su base de precios?
function A.Available()
  local api = Auctionator and Auctionator.API and Auctionator.API.v1
  return api ~= nil and api.GetAuctionPriceByItemID ~= nil and Database() ~= nil
end

-- Precio mínimo por unidad que vio Auctionator la última vez, o nil.
function ns.LivePrice(itemID)
  if not itemID or not A.Available() then return nil end
  local ok, price = pcall(Auctionator.API.v1.GetAuctionPriceByItemID, ADDON, itemID)
  if ok and type(price) == "number" and price > 0 then return price end
  return nil
end

local function Num(n)
  return ("%.0f"):format(n)
end

-- Copia la base de precios de Auctionator (la del reino actual) para el motor.
-- items[itemID] = "último|día:mínimo:máximo:unidades;..." (días contados desde el día 0 de Auctionator).
function A.Export()
  local database = Database()
  local db = database and database.db
  local day0 = Auctionator and Auctionator.Constants and Auctionator.Constants.SCAN_DAY_0
  if type(db) ~= "table" or not day0 then return end
  local now = time()
  local today = math.floor((now - day0) / DAY)
  local items, count = {}, 0
  for key, data in pairs(db) do
    local itemID = tonumber(key)  -- el equipo con nivel de objeto va con otra clave: no se copia
    if itemID and type(data) == "table" and type(data.m) == "number" and data.m > 0 then
      local parts = {}
      for day, high in pairs(type(data.h) == "table" and data.h or {}) do
        local d = tonumber(day)
        if d and type(high) == "number" and d > today - HISTORY_DAYS then
          local low = type(data.l) == "table" and data.l[day] or high
          local units = type(data.a) == "table" and data.a[day] or 0
          parts[#parts + 1] = d .. ":" .. Num(low) .. ":" .. Num(high) .. ":" .. Num(units)
        end
      end
      if #parts > 0 then
        table.sort(parts)
        items[itemID] = Num(data.m) .. "|" .. table.concat(parts, ";")
        count = count + 1
      end
    end
  end
  PitiGoldsDB.auctionator = {
    realm = Auctionator.State and Auctionator.State.CurrentRealm or GetRealmName(),
    faction = UnitFactionGroup("player"),
    char = ns.charKey,
    time = now,
    day0 = day0,
    today = today,
    count = count,
    items = items,
  }
end

ns.On("PLAYER_LOGOUT", function()
  local ok, err = pcall(A.Export)
  if not ok then ns.Log("ERROR copiando los precios de Auctionator: " .. tostring(err)) end
end)

-- Aviso -------------------------------------------------------------------------------------

local MISSING = "no encuentro Auctionator. PitiGolds saca todos los precios de la subasta de"
  .. " Auctionator: instálalo (con WowUp) y escanea la subasta con él."

function A.Warn()
  if A.Available() then return false end
  ns.Print("|cffff4040" .. MISSING .. "|r")
  if UIErrorsFrame and UIErrorsFrame.AddMessage then
    UIErrorsFrame:AddMessage("PitiGolds: falta Auctionator (precios de la subasta)", 1, 0.25, 0.25)
  end
  return true
end

ns.On("PLAYER_LOGIN", function()
  C_Timer.After(5, function() A.Warn() end)
end)

-- Cuando Auctionator apunta precios nuevos (su escaneo o lo que buscas), se rehacen las cuentas a
-- la vista: ventana de profesión, cajones, libranzas y el panel.
local hooked = false
local function HookPrices()
  local database = Database()
  if hooked or not database or type(database.SetPrice) ~= "function" then return end
  hooked = true
  hooksecurefunc(database, "SetPrice", function()
    ns.Debounce("auctionator", 1, function()
      if ns.OnLivePrices then ns.OnLivePrices() end
      if ns.RefreshUI then ns.RefreshUI() end
    end)
  end)
end
ns.On("PLAYER_LOGIN", HookPrices)
ns.On("AUCTION_HOUSE_SHOW", HookPrices)

ns.Command("auctionator", "dice si se están leyendo los precios de Auctionator", function()
  if A.Warn() then return end
  local db = Database().db
  local n = 0
  for _ in pairs(type(db) == "table" and db or {}) do n = n + 1 end
  ns.Print(("precios de Auctionator: %d objetos. Se copian para el motor al salir o con /reload."):format(n))
end)
