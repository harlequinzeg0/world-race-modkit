//! Finds a game path in the session's file roots, first root first.

pub fn resolve(roots: &[String], path: &str, exists: impl Fn(&str) -> bool) -> Option<String> {
    let relative = path.replace('\\', "/");
    roots.iter().map(|root| format!("{root}/{relative}")).find(|full| exists(full))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn roots() -> Vec<String> {
        vec!["gen".to_string(), "mod_a".to_string(), "mod_b".to_string()]
    }

    #[test]
    fn first_root_holding_the_path_wins() {
        let found = resolve(&roots(), "misc/a.xml", |p| p == "mod_a/misc/a.xml" || p == "mod_b/misc/a.xml");
        assert_eq!(found.as_deref(), Some("mod_a/misc/a.xml"));
    }

    #[test]
    fn backslashes_become_forward_slashes() {
        let found = resolve(&roots(), "misc\\cache\\a.xml", |p| p == "gen/misc/cache/a.xml");
        assert_eq!(found.as_deref(), Some("gen/misc/cache/a.xml"));
    }

    #[test]
    fn no_root_means_none() {
        assert_eq!(resolve(&roots(), "misc/a.xml", |_| false), None);
    }
}
