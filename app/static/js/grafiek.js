/* ==========================================================================
   Lichtgewicht lijngrafiek in SVG - zonder externe bibliotheken.

   Bewust geen Chart.js of D3: de Raspberry Pi draait vaak zonder internet,
   en dit bestand is klein genoeg om direct mee te laden.

   Gebruik:
     const grafiek = new Lijngrafiek(element, { kleur, eenheid, decimalen });
     grafiek.zet(punten);            // punten: [{ tijd: Date, waarde: number|null }]
   ========================================================================== */

(function (globaal) {
    "use strict";

    var HOOGTE = 170;
    var MARGE = { boven: 12, rechts: 12, onder: 24, links: 42 };

    function stijlwaarde(naam, terugval) {
        var waarde = getComputedStyle(document.documentElement)
            .getPropertyValue(naam)
            .trim();
        return waarde || terugval;
    }

    /** Rondt een stapgrootte af naar 1, 2, 2.5 of 5 maal een macht van tien. */
    function mooieStap(ruw) {
        if (!isFinite(ruw) || ruw <= 0) { return 1; }
        var macht = Math.pow(10, Math.floor(Math.log10(ruw)));
        var rest = ruw / macht;
        var stap;
        if (rest <= 1) { stap = 1; }
        else if (rest <= 2) { stap = 2; }
        else if (rest <= 2.5) { stap = 2.5; }
        else if (rest <= 5) { stap = 5; }
        else { stap = 10; }
        return stap * macht;
    }

    function formatteer(waarde, decimalen) {
        if (waarde === null || waarde === undefined || isNaN(waarde)) { return "--"; }
        return Number(waarde).toLocaleString("nl-NL", {
            minimumFractionDigits: decimalen,
            maximumFractionDigits: decimalen
        });
    }

    function tijdLabel(datum, spanMs) {
        if (spanMs > 3 * 24 * 3600 * 1000) {
            return datum.toLocaleDateString("nl-NL", { day: "2-digit", month: "2-digit" });
        }
        return datum.toLocaleTimeString("nl-NL", { hour: "2-digit", minute: "2-digit" });
    }

    function tijdVolledig(datum) {
        return datum.toLocaleString("nl-NL", {
            day: "2-digit", month: "2-digit",
            hour: "2-digit", minute: "2-digit"
        });
    }

    function maak(naam, kenmerken) {
        var element = document.createElementNS("http://www.w3.org/2000/svg", naam);
        Object.keys(kenmerken || {}).forEach(function (sleutel) {
            element.setAttribute(sleutel, kenmerken[sleutel]);
        });
        return element;
    }

    function Lijngrafiek(houder, opties) {
        this.houder = houder;
        this.opties = Object.assign({
            kleur: "var(--serie-1)",
            eenheid: "",
            decimalen: 1,
            naam: "",
            hoogte: HOOGTE,
            leegTekst: "Nog geen metingen in deze periode."
        }, opties || {});
        this.punten = [];

        this.tip = document.createElement("div");
        this.tip.className = "grafiek-tip";
        this.houder.appendChild(this.tip);

        var self = this;
        this._hertekenen = function () { self.teken(); };

        if (typeof ResizeObserver === "function") {
            var wachtend = null;
            this._observer = new ResizeObserver(function () {
                clearTimeout(wachtend);
                wachtend = setTimeout(self._hertekenen, 80);
            });
            this._observer.observe(this.houder);
        } else {
            window.addEventListener("resize", this._hertekenen);
        }
    }

    Lijngrafiek.prototype.zet = function (punten) {
        this.punten = (punten || []).filter(function (punt) {
            return punt && punt.tijd instanceof Date && !isNaN(punt.tijd.getTime());
        });
        this.teken();
    };

    Lijngrafiek.prototype.teken = function () {
        var breedte = Math.max(220, Math.floor(this.houder.clientWidth) || 320);
        var hoogte = this.opties.hoogte;

        var oud = this.houder.querySelector("svg");
        if (oud) { oud.remove(); }
        var leeg = this.houder.querySelector(".grafiek-leeg");
        if (leeg) { leeg.remove(); }

        var metWaarde = this.punten.filter(function (punt) {
            return punt.waarde !== null && punt.waarde !== undefined && !isNaN(punt.waarde);
        });

        if (metWaarde.length === 0) {
            var bericht = document.createElement("p");
            bericht.className = "grafiek-leeg";
            bericht.textContent = this.opties.leegTekst;
            this.houder.appendChild(bericht);
            this.tip.classList.remove("zichtbaar");
            return;
        }

        var kleur = this.opties.kleur;
        var rasterKleur = stijlwaarde("--raster", "#e8e8e4");
        var tekstKleur = stijlwaarde("--tekst-gedempt", "#76746f");
        var vlakKleur = stijlwaarde("--plot-vlak", "#ffffff");

        var tMin = this.punten[0].tijd.getTime();
        var tMax = this.punten[this.punten.length - 1].tijd.getTime();
        if (tMax <= tMin) { tMax = tMin + 60000; }

        var waarden = metWaarde.map(function (punt) { return Number(punt.waarde); });
        var yMin = Math.min.apply(null, waarden);
        var yMax = Math.max.apply(null, waarden);
        if (yMax - yMin < 1e-9) { yMin -= 1; yMax += 1; }

        var stap = mooieStap((yMax - yMin) / 3);
        var onder = Math.floor(yMin / stap) * stap;
        var boven = Math.ceil(yMax / stap) * stap;
        if (boven - onder < stap) { boven = onder + stap; }

        var plotBreedte = breedte - MARGE.links - MARGE.rechts;
        var plotHoogte = hoogte - MARGE.boven - MARGE.onder;

        function xVan(tijd) {
            return MARGE.links + ((tijd - tMin) / (tMax - tMin)) * plotBreedte;
        }
        function yVan(waarde) {
            return MARGE.boven + (1 - (waarde - onder) / (boven - onder)) * plotHoogte;
        }

        var svg = maak("svg", {
            viewBox: "0 0 " + breedte + " " + hoogte,
            width: breedte,
            height: hoogte,
            role: "presentation",
            focusable: "false"
        });

        /* --- Rasterlijnen: dun, doorgetrokken, terughoudend ---------------- */
        for (var waarde = onder; waarde <= boven + 1e-9; waarde += stap) {
            var y = yVan(waarde);
            svg.appendChild(maak("line", {
                x1: MARGE.links, y1: y, x2: breedte - MARGE.rechts, y2: y,
                stroke: rasterKleur, "stroke-width": 1, "shape-rendering": "crispEdges"
            }));
            var tekst = maak("text", {
                x: MARGE.links - 7, y: y + 3.5,
                "text-anchor": "end", fill: tekstKleur, "font-size": 10.5
            });
            tekst.textContent = formatteer(waarde, this.opties.decimalen === 0 ? 0 : 1);
            svg.appendChild(tekst);
        }

        /* --- Tijdlabels onderaan ------------------------------------------ */
        var span = tMax - tMin;
        var aantalLabels = breedte < 380 ? 3 : 4;
        for (var i = 0; i < aantalLabels; i += 1) {
            var deel = i / (aantalLabels - 1);
            var tijdstip = new Date(tMin + span * deel);
            var xLabel = MARGE.links + plotBreedte * deel;
            var anker = i === 0 ? "start" : (i === aantalLabels - 1 ? "end" : "middle");
            var tijdTekst = maak("text", {
                x: xLabel, y: hoogte - 7,
                "text-anchor": anker, fill: tekstKleur, "font-size": 10.5
            });
            tijdTekst.textContent = tijdLabel(tijdstip, span);
            svg.appendChild(tijdTekst);
        }

        /* --- Vlak onder de lijn: een wassing van 10%, geen dichte blok ----- */
        var segmenten = [];
        var huidig = [];
        this.punten.forEach(function (punt) {
            if (punt.waarde === null || punt.waarde === undefined || isNaN(punt.waarde)) {
                if (huidig.length) { segmenten.push(huidig); huidig = []; }
                return;
            }
            huidig.push(punt);
        });
        if (huidig.length) { segmenten.push(huidig); }

        segmenten.forEach(function (segment) {
            if (segment.length < 2) { return; }
            var vlakPad = "M " + xVan(segment[0].tijd.getTime()) + " " + yVan(onder);
            segment.forEach(function (punt) {
                vlakPad += " L " + xVan(punt.tijd.getTime()) + " " + yVan(punt.waarde);
            });
            vlakPad += " L " + xVan(segment[segment.length - 1].tijd.getTime()) + " " + yVan(onder) + " Z";
            svg.appendChild(maak("path", {
                d: vlakPad, fill: kleur, "fill-opacity": 0.1, stroke: "none"
            }));
        });

        segmenten.forEach(function (segment) {
            var pad = segment.map(function (punt, index) {
                return (index === 0 ? "M " : "L ") +
                    xVan(punt.tijd.getTime()) + " " + yVan(punt.waarde);
            }).join(" ");
            svg.appendChild(maak("path", {
                d: pad, fill: "none", stroke: kleur, "stroke-width": 2,
                "stroke-linejoin": "round", "stroke-linecap": "round"
            }));
            if (segment.length === 1) {
                svg.appendChild(maak("circle", {
                    cx: xVan(segment[0].tijd.getTime()), cy: yVan(segment[0].waarde),
                    r: 4, fill: kleur, stroke: vlakKleur, "stroke-width": 2
                }));
            }
        });

        /* --- Eindpunt: gevulde stip met een ring in de vlakkleur ----------- */
        var laatste = metWaarde[metWaarde.length - 1];
        svg.appendChild(maak("circle", {
            cx: xVan(laatste.tijd.getTime()), cy: yVan(laatste.waarde),
            r: 4.5, fill: kleur, stroke: vlakKleur, "stroke-width": 2
        }));

        /* --- Laag voor het zweven met de muis ------------------------------ */
        var kruis = maak("line", {
            x1: 0, y1: MARGE.boven, x2: 0, y2: MARGE.boven + plotHoogte,
            stroke: rasterKleur, "stroke-width": 1, opacity: 0
        });
        svg.appendChild(kruis);

        var zweefStip = maak("circle", {
            cx: 0, cy: 0, r: 4.5, fill: kleur,
            stroke: vlakKleur, "stroke-width": 2, opacity: 0
        });
        svg.appendChild(zweefStip);

        var vangvlak = maak("rect", {
            x: MARGE.links, y: MARGE.boven,
            width: plotBreedte, height: plotHoogte,
            fill: "transparent"
        });
        svg.appendChild(vangvlak);

        this.houder.insertBefore(svg, this.tip);
        this._koppelZweven(svg, vangvlak, kruis, zweefStip, metWaarde, xVan, yVan, breedte);
    };

    Lijngrafiek.prototype._koppelZweven = function (
        svg, vangvlak, kruis, stip, punten, xVan, yVan, breedte
    ) {
        var self = this;

        function verberg() {
            kruis.setAttribute("opacity", 0);
            stip.setAttribute("opacity", 0);
            self.tip.classList.remove("zichtbaar");
        }

        function toon(gebeurtenis) {
            var kader = svg.getBoundingClientRect();
            var schaal = kader.width / breedte || 1;
            var muisX = (gebeurtenis.clientX - kader.left) / schaal;

            var dichtstbij = punten[0];
            var kleinsteAfstand = Infinity;
            punten.forEach(function (punt) {
                var afstand = Math.abs(xVan(punt.tijd.getTime()) - muisX);
                if (afstand < kleinsteAfstand) {
                    kleinsteAfstand = afstand;
                    dichtstbij = punt;
                }
            });

            var x = xVan(dichtstbij.tijd.getTime());
            var y = yVan(dichtstbij.waarde);

            kruis.setAttribute("x1", x);
            kruis.setAttribute("x2", x);
            kruis.setAttribute("opacity", 1);
            stip.setAttribute("cx", x);
            stip.setAttribute("cy", y);
            stip.setAttribute("opacity", 1);

            self.tip.innerHTML = "";
            var tijdRegel = document.createElement("div");
            tijdRegel.textContent = tijdVolledig(dichtstbij.tijd);
            var waardeRegel = document.createElement("b");
            waardeRegel.textContent =
                formatteer(dichtstbij.waarde, self.opties.decimalen) +
                (self.opties.eenheid ? " " + self.opties.eenheid : "");
            self.tip.appendChild(tijdRegel);
            self.tip.appendChild(waardeRegel);

            self.tip.style.left = (x * schaal) + "px";
            self.tip.style.top = (y * schaal) + "px";
            self.tip.classList.add("zichtbaar");
        }

        vangvlak.addEventListener("mousemove", toon);
        vangvlak.addEventListener("mouseleave", verberg);
        vangvlak.addEventListener("touchstart", function (gebeurtenis) {
            if (gebeurtenis.touches.length) { toon(gebeurtenis.touches[0]); }
        }, { passive: true });
        vangvlak.addEventListener("touchmove", function (gebeurtenis) {
            if (gebeurtenis.touches.length) { toon(gebeurtenis.touches[0]); }
        }, { passive: true });
        vangvlak.addEventListener("touchend", verberg);
    };

    globaal.Lijngrafiek = Lijngrafiek;
    globaal.grafiekHulp = { formatteer: formatteer, tijdVolledig: tijdVolledig };
}(window));
