import { useMemo, useState } from "react";
import { api } from "../api/client";
import type { Department, Task, User } from "../api/types";
import { IconPlus } from "../components/icons";
import { PageHeader } from "../components/Shell";
import { Badge, Button, ConfirmModal, Empty, Field, Modal, Panel, Segmented } from "../components/ui";
import { useAppData } from "../state/appdata";
import { useToast } from "../state/toasts";
import { dateTime } from "../lib/format";

const SWATCHES = ["#1D3F91", "#2F7D5B", "#A2541B", "#7A4BA8", "#B3263E", "#1F7A8C", "#6B7A1F", "#5B6875"];

function useSave() {
  const toast = useToast();
  const { refreshOrg } = useAppData();
  return async (fn: () => Promise<unknown>, okMsg: string) => {
    try {
      await fn();
      await refreshOrg();
      toast.push("success", okMsg);
      return true;
    } catch (e) {
      toast.error(e, "Couldn't save");
      return false;
    }
  };
}

// --------------------------------------------------------------------------- departments

function DepartmentModal({ dept, open, onClose }: { dept: Partial<Department> | null; open: boolean; onClose: () => void }) {
  const save = useSave();
  const [name, setName] = useState("");
  const [color, setColor] = useState(SWATCHES[0]);
  const [desc, setDesc] = useState("");
  const [key, setKey] = useState<unknown>(null);
  if (open && key !== dept) {
    setKey(dept);
    setName(dept?.name ?? "");
    setColor(dept?.color ?? SWATCHES[0]);
    setDesc(dept?.description ?? "");
  }
  const editing = !!dept?.id;
  const submit = async () => {
    const body = { name: name.trim(), color, description: desc };
    const ok = await save(
      () => (editing ? api.patch(`/api/departments/${dept!.id}`, body) : api.post("/api/departments", body)),
      editing ? `Saved ${body.name}` : `Added ${body.name}`,
    );
    if (ok) onClose();
  };
  return (
    <Modal
      open={open}
      title={editing ? `Edit ${dept?.name}` : "Add a department"}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" onClick={() => void submit()} disabled={!name.trim()}>
            {editing ? "Save department" : "Add department"}
          </Button>
        </>
      }
    >
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <Field label="Name">
          <input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Household tasks" data-autofocus autoFocus />
        </Field>
        <Field label="Color" hint="Used to tell departments apart in lists and plots.">
          <div className="swatches">
            {SWATCHES.map((c) => (
              <button key={c} type="button" className={`swatch ${c === color ? "on" : ""}`} style={{ background: c }} onClick={() => setColor(c)} aria-label={`Color ${c}`} />
            ))}
          </div>
        </Field>
        <Field label="Description (optional)">
          <textarea rows={2} value={desc} onChange={(e) => setDesc(e.target.value)} placeholder="What kind of tasks this group records" />
        </Field>
      </form>
    </Modal>
  );
}

// --------------------------------------------------------------------------- people

function PersonModal({ user, open, onClose }: { user: Partial<User> | null; open: boolean; onClose: () => void }) {
  const save = useSave();
  const { departments } = useAppData();
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<"operator" | "admin">("operator");
  const [depts, setDepts] = useState<number[]>([]);
  const [key, setKey] = useState<unknown>(null);
  if (open && key !== user) {
    setKey(user);
    setName(user?.name ?? "");
    setEmail(user?.email ?? "");
    setRole(user?.role ?? "operator");
    setDepts(user?.department_ids ?? []);
  }
  const editing = !!user?.id;
  const submit = async () => {
    const body = { name: name.trim(), email: email.trim() || null, role, department_ids: depts };
    const ok = await save(() => (editing ? api.patch(`/api/users/${user!.id}`, body) : api.post("/api/users", body)), editing ? `Saved ${body.name}` : `Added ${body.name}`);
    if (ok) onClose();
  };
  return (
    <Modal
      open={open}
      title={editing ? `Edit ${user?.name}` : "Add a person"}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" onClick={() => void submit()} disabled={!name.trim()}>
            {editing ? "Save person" : "Add person"}
          </Button>
        </>
      }
    >
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <Field label="Name" hint="Shown in the operator picker and on every episode they record.">
          <input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="First and last name" autoFocus />
        </Field>
        <Field label="Email (optional)">
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="name@lab.org" />
        </Field>
        <Field label="Role" hint="Admins can change calibration and station settings. There are no passwords; access is controlled by who can use this PC.">
          <Segmented
            value={role}
            options={[
              { value: "operator", label: "Operator" },
              { value: "admin", label: "Admin" },
            ]}
            onChange={setRole}
          />
        </Field>
        <div className="field">
          <span className="field-label">Departments</span>
          {departments.length === 0 && <span className="field-hint">Add a department first.</span>}
          <div className="check-list">
            {departments.map((d) => (
              <label key={d.id} className="check-item">
                <input type="checkbox" checked={depts.includes(d.id)} onChange={() => setDepts(depts.includes(d.id) ? depts.filter((x) => x !== d.id) : [...depts, d.id])} />
                <span className="dept-dot" style={{ background: d.color }} />
                {d.name}
              </label>
            ))}
          </div>
        </div>
      </form>
    </Modal>
  );
}

// --------------------------------------------------------------------------- tasks

function TaskModal({ task, open, onClose }: { task: Partial<Task> | null; open: boolean; onClose: () => void }) {
  const save = useSave();
  const { departments } = useAppData();
  const [name, setName] = useState("");
  const [desc, setDesc] = useState("");
  const [dept, setDept] = useState<string>("");
  const [key, setKey] = useState<unknown>(null);
  if (open && key !== task) {
    setKey(task);
    setName(task?.name ?? "");
    setDesc(task?.description ?? "");
    setDept(task?.department_id ? String(task.department_id) : "");
  }
  const editing = !!task?.id;
  const submit = async () => {
    const body = { name: name.trim(), description: desc, department_id: dept ? +dept : null };
    const ok = await save(() => (editing ? api.patch(`/api/tasks/${task!.id}`, body) : api.post("/api/tasks", body)), editing ? `Saved ${body.name}` : `Added ${body.name}`);
    if (ok) onClose();
  };
  return (
    <Modal
      open={open}
      title={editing ? `Edit ${task?.name}` : "Add a task"}
      onClose={onClose}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" onClick={() => void submit()} disabled={!name.trim()}>
            {editing ? "Save task" : "Add task"}
          </Button>
        </>
      }
    >
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <Field label="Task name" hint="Becomes part of the episode folder name, so keep it short.">
          <input type="text" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Fold towel" autoFocus />
        </Field>
        <Field label="Department">
          <select value={dept} onChange={(e) => setDept(e.target.value)}>
            <option value="">Any department</option>
            {departments.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Instructions for operators (optional)" hint="Saved with each episode as the language instruction for training.">
          <textarea rows={3} value={desc} onChange={(e) => setDesc(e.target.value)} placeholder="What a successful episode looks like" />
        </Field>
      </form>
    </Modal>
  );
}

// --------------------------------------------------------------------------- page

export function OrganizationPage() {
  const { departments, users, tasks } = useAppData();
  const save = useSave();
  const [deptModal, setDeptModal] = useState<Partial<Department> | null>(null);
  const [userModal, setUserModal] = useState<Partial<User> | null>(null);
  const [taskModal, setTaskModal] = useState<Partial<Task> | null>(null);
  const [showInactive, setShowInactive] = useState(false);
  const [delDept, setDelDept] = useState<Department | null>(null);
  const [delTask, setDelTask] = useState<Task | null>(null);

  const people = useMemo(() => users.filter((u) => showInactive || u.active).sort((a, b) => Number(b.active) - Number(a.active) || a.name.localeCompare(b.name)), [users, showInactive]);
  const inactiveCount = users.filter((u) => !u.active).length;
  const deptName = (id: number | null) => departments.find((d) => d.id === id)?.name;

  return (
    <div className="page">
      <PageHeader title="People and departments" lead="Everyone who records on this station. Episodes are filed under the department and person chosen in the top bar." />

      <div className="org-grid">
        <Panel
          title="Departments"
          subtitle={`${departments.length} department${departments.length === 1 ? "" : "s"}`}
          actions={
            <Button size="sm" icon={<IconPlus size={16} />} onClick={() => setDeptModal({})}>
              Add department
            </Button>
          }
          pad={false}
          className="org-depts"
        >
          {departments.length === 0 && <Empty title="No departments yet">Departments group people and tasks, and decide which folder each episode goes into.</Empty>}
          <ul className="dept-list">
            {departments.map((d) => (
              <li key={d.id}>
                <span className="dept-bar" style={{ background: d.color }} />
                <div className="dept-text">
                  <div className="dept-name">{d.name}</div>
                  {d.description && <div className="dept-desc">{d.description}</div>}
                  <div className="dept-counts tnum">
                    {d.user_count} {d.user_count === 1 ? "person" : "people"}, {d.episode_count} episode{d.episode_count === 1 ? "" : "s"}, {tasks.filter((t) => t.department_id === d.id).length} task
                    {tasks.filter((t) => t.department_id === d.id).length === 1 ? "" : "s"}
                  </div>
                </div>
                <div className="row-actions">
                  <Button variant="ghost" size="sm" onClick={() => setDeptModal(d)}>
                    Edit
                  </Button>
                  <Button variant="ghost" size="sm" onClick={() => setDelDept(d)} disabled={d.episode_count > 0} title={d.episode_count > 0 ? "Departments with episodes can't be deleted" : undefined}>
                    Delete
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        </Panel>

        <Panel
          title="Tasks"
          subtitle="What operators pick before recording"
          actions={
            <Button size="sm" icon={<IconPlus size={16} />} onClick={() => setTaskModal({})}>
              Add task
            </Button>
          }
          pad={false}
          className="org-tasks"
        >
          {tasks.length === 0 && <Empty title="No tasks yet">Add the tasks your team records, like "Fold towel". Operators choose one before each recording.</Empty>}
          <ul className="task-list">
            {tasks.map((t) => (
              <li key={t.id}>
                <div className="task-text">
                  <div className="task-name">{t.name}</div>
                  <div className="task-meta">
                    {deptName(t.department_id) ?? "Any department"}
                    {t.description && <span className="task-desc">{t.description}</span>}
                  </div>
                </div>
                <div className="row-actions">
                  <Button variant="ghost" size="sm" onClick={() => setTaskModal(t)}>
                    Edit
                  </Button>
                  <Button variant="ghost" size="sm" onClick={() => setDelTask(t)}>
                    Delete
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        </Panel>
      </div>

      <Panel
        title="People"
        subtitle={`${users.filter((u) => u.active).length} active${inactiveCount ? `, ${inactiveCount} inactive` : ""}`}
        actions={
          <>
            {inactiveCount > 0 && (
              <Button variant="ghost" size="sm" onClick={() => setShowInactive(!showInactive)}>
                {showInactive ? "Hide inactive" : "Show inactive"}
              </Button>
            )}
            <Button size="sm" variant="primary" icon={<IconPlus size={16} />} onClick={() => setUserModal({})}>
              Add person
            </Button>
          </>
        }
        pad={false}
        className="org-people"
      >
        {people.length === 0 ? (
          <Empty title="No one has been added yet" action={<Button variant="primary" onClick={() => setUserModal({})}>Add the first person</Button>}>
            Add each operator once. They'll appear in the operator picker at the top of every page.
          </Empty>
        ) : (
          <table className="table people-table">
            <thead>
              <tr>
                <th>Name</th>
                <th>Role</th>
                <th>Departments</th>
                <th className="num">Episodes</th>
                <th>Added</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {people.map((u) => (
                <tr key={u.id} className={u.active ? "" : "inactive"} onClick={() => setUserModal(u)}>
                  <td>
                    <div className="person">
                      <span className="avatar" aria-hidden="true">
                        {u.name
                          .split(" ")
                          .map((p) => p[0])
                          .slice(0, 2)
                          .join("")}
                      </span>
                      <div>
                        <div className="strong">{u.name}</div>
                        {u.email && <div className="muted small">{u.email}</div>}
                      </div>
                    </div>
                  </td>
                  <td>{u.role === "admin" ? <Badge tone="primary">Admin</Badge> : "Operator"}</td>
                  <td>
                    <div className="dept-chips">
                      {u.department_ids.length === 0 && <span className="muted">None</span>}
                      {u.department_ids.map((id) => {
                        const d = departments.find((x) => x.id === id);
                        return d ? (
                          <span key={id} className="dept-chip">
                            <span className="dept-dot" style={{ background: d.color }} />
                            {d.name}
                          </span>
                        ) : null;
                      })}
                    </div>
                  </td>
                  <td className="num tnum">{u.episode_count}</td>
                  <td className="muted nowrap">{dateTime(u.created_at)}</td>
                  <td className="num" onClick={(e) => e.stopPropagation()}>
                    {u.active ? (
                      <Button variant="ghost" size="sm" onClick={() => void save(() => api.patch(`/api/users/${u.id}`, { active: false }), `${u.name} deactivated`)}>
                        Deactivate
                      </Button>
                    ) : (
                      <Button variant="secondary" size="sm" onClick={() => void save(() => api.patch(`/api/users/${u.id}`, { active: true }), `${u.name} reactivated`)}>
                        Reactivate
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Panel>

      <DepartmentModal dept={deptModal} open={!!deptModal} onClose={() => setDeptModal(null)} />
      <PersonModal user={userModal} open={!!userModal} onClose={() => setUserModal(null)} />
      <TaskModal task={taskModal} open={!!taskModal} onClose={() => setTaskModal(null)} />
      <ConfirmModal
        open={!!delDept}
        title={`Delete ${delDept?.name}?`}
        danger
        confirmLabel="Delete department"
        onClose={() => setDelDept(null)}
        onConfirm={async () => {
          const d = delDept!;
          setDelDept(null);
          await save(() => api.del(`/api/departments/${d.id}`), `Deleted ${d.name}`);
        }}
        body="People stay in the organization; they're only removed from this department."
      />
      <ConfirmModal
        open={!!delTask}
        title={`Delete ${delTask?.name}?`}
        danger
        confirmLabel="Delete task"
        onClose={() => setDelTask(null)}
        onConfirm={async () => {
          const t = delTask!;
          setDelTask(null);
          await save(() => api.del(`/api/tasks/${t.id}`), `Deleted ${t.name}`);
        }}
        body="Episodes already recorded for this task keep their task name."
      />
    </div>
  );
}
