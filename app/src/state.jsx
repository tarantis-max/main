import { createContext, useContext, useEffect, useState } from "react";
import { api } from "./api.js";

/** Global app state: the list of visible Jira projects and the current
 *  selection (persisted in localStorage so it survives reloads). */
const ProjectCtx = createContext(null);

export function ProjectProvider({ children }) {
  const [projects, setProjects] = useState([]);
  const [project, setProjectRaw] = useState(localStorage.getItem("mu.project") || "");
  const [ready, setReady] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    (async () => {
      try {
        const data = await api("/api/jira/projects");
        setProjects(data.projects || []);
        setProjectRaw((cur) => {
          const keys = (data.projects || []).map((p) => p.key);
          if (cur && keys.includes(cur)) return cur;
          return keys.includes(data.default) ? data.default : keys[0] || "";
        });
      } catch (e) {
        setError(String(e.message || e));
      } finally {
        setReady(true);
      }
    })();
  }, []);

  const setProject = (key) => {
    localStorage.setItem("mu.project", key);
    setProjectRaw(key);
  };

  const current = projects.find((p) => p.key === project) || null;
  return (
    <ProjectCtx.Provider value={{ projects, project, current, setProject, ready, error }}>
      {children}
    </ProjectCtx.Provider>
  );
}

export const useProject = () => useContext(ProjectCtx);
