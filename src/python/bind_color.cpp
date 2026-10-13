// `uzpainter.colormanagement`: the colour of a uniform source and the project's colour-management
// state (bindings.h).
//
// The native `Color` keeps exactly what the caller gave: `value_raw` and the colour space
// (`GenericColorSpace` member name or any string; None when not given). A uniform source stores
// Painter's working value of it, in the Working space (`python::StoredUniformColour`, decision
// 240), so `get_color` reads back what Painter reads back. The facade's conversions between spaces
// (`Color.convert`, `.sRGB`, `.working`) are its own (phase1.20_pyapi-facade); its decode into the
// working space is the native one, through the private `_working_value`.

#include "python/bindings.h"
#include "python/edits.h"
#include "python/errors.h"

namespace uzp::python {

namespace {

enum class GenericColorSpace { Raw, Working, sRGB };

const char* Name(GenericColorSpace space) {
    switch (space) {
        case GenericColorSpace::Raw: return "Raw";
        case GenericColorSpace::Working: return "Working";
        case GenericColorSpace::sRGB: return "sRGB";
    }
    return "Raw";
}

std::optional<std::string> SpaceOf(const py::object& space) {
    if (space.is_none()) return std::nullopt;
    if (py::isinstance<py::str>(space)) return space.cast<std::string>();
    if (py::isinstance<GenericColorSpace>(space)) return std::string(Name(space.cast<GenericColorSpace>()));
    throw py::type_error("color_space must be a GenericColorSpace, a str or None");
}

}  // namespace

void BindColor(py::module_& m) {
    py::enum_<GenericColorSpace>(m, "GenericColorSpace")
        .value("Raw", GenericColorSpace::Raw)
        .value("Working", GenericColorSpace::Working)
        .value("sRGB", GenericColorSpace::sRGB);

    py::class_<Color> color(m, "Color", "r, g, b in `color_space` (a GenericColorSpace, a str, or None).");
    color
        .def(py::init([](double r, double g, double b, const py::object& space) {
                 return Color{{r, g, b}, SpaceOf(space)};
             }),
             py::arg("r"), py::arg("g"), py::arg("b"), py::arg("color_space") = py::none())
        .def_property_readonly("value_raw",
                               [](const Color& c) { return py::make_tuple(c.value_raw[0], c.value_raw[1], c.value_raw[2]); })
        .def_property_readonly("color_space", [](const Color& c) -> py::object {
            return c.color_space ? py::object(py::str(*c.color_space)) : py::none();
        })
        .def("__eq__", [](const Color& a, const Color& b) { return a.value_raw == b.value_raw && a.color_space == b.color_space; })
        .def("__repr__", [](const Color& c) {
            return "Color(" + core::json::FormatDouble(c.value_raw[0]) + ", " + core::json::FormatDouble(c.value_raw[1]) +
                   ", " + core::json::FormatDouble(c.value_raw[2]) + ", " + (c.color_space ? "'" + *c.color_space + "'" : "None") + ")";
        });
    color.attr("__hash__") = py::none();
    SealClass(color);

    m.def(
        "get_color_management",
        [] {
            const core::ColorManagement& cm = Read()->settings.color_management;
            core::json::Object o{{"config_hash", cm.config_hash}, {"io_rules", cm.io_rules}, {"mode", cm.mode},
                                 {"working_space", cm.working_space}};
            return FromJson(o);
        },
        "The project's colour-management state: mode, working space, configuration hash and I/O rules.");

    // Private: the facade's decode (python/uzpainter_facade/colour.py `working_value`), so the facade
    // and every native setter compute a stored uniform colour once (`python::WorkingColour`).
    m.def(
        "_working_value",
        [](double r, double g, double b, const std::optional<std::string>& color_space, bool decodes, bool ocio) {
            const std::array<double, 3> working = WorkingColour({r, g, b}, color_space, decodes, ocio);
            return py::make_tuple(working[0], working[1], working[2]);
        },
        py::arg("r"), py::arg("g"), py::arg("b"), py::arg("color_space"), py::arg("decodes"), py::arg("ocio"),
        "The float32 working value Painter stores for (r, g, b) in `color_space` (None: unset) on a channel that "
        "`decodes` an sRGB colour or not, under OCIO with Painter's substance config (`ocio`) or Legacy (decision 240).");
}

}  // namespace uzp::python
