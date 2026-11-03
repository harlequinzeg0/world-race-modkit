fn main() {
    // A .def file with a LIBRARY line would also turn the test program into a DLL.
    println!("cargo:rustc-cdylib-link-arg=/EXPORT:DirectInput8Create=_DirectInput8Create@20");
}
